# python3
"""HHL algorithm."""

# HLL is an ADVANCED ALGORIHM. For study it is recommended
# to first become proficient with these key concepts:
#   basis changes
#   phase estimation
#   quantum Fourier transformation
#   Hamiltonian simulation
#
# This version (compared to hhl_2x2.py is more general and
# will be extended to support 4x4 matrices as well. The
# numerical comparisons to a reference numerical example
# have been removed.

from absl import app
import numpy as np

from src.lib import circuit
from src.lib import ops
from src.lib import state


def check_classic_solution(a, b, verify):
  """Check classic solution, verify against paper values."""

  x = np.linalg.solve(a, b)
  for i in range(1, 2 ** b.nbits):
    ratio_x = np.real((x[i] * x[i].conj()) / (x[0] * x[0].conj()))
    print(f'Classic solution^2 ratio: {ratio_x:.3f}')
  return ratio_x


def check_results(qc, a, b, verify):
  """Check the results by inspecting the final state."""

  ratio_classical = check_classic_solution(a, b, verify)

  res = (qc.psi > 0.001).nonzero()[0]
  for j in range(1, b.size):
    ratio_quantum = np.real(qc.psi[res[j]]**2 / qc.psi[res[0]]**2)
    print(f'Quantum solution^2 ratio: {ratio_quantum:.3f}\n')
    if not np.allclose(ratio_classical, ratio_quantum, atol=1e-4):
      raise AssertionError('Incorrect result.')


def compute_sorted_eigenvalues(a, verify: bool = True):
  """Compute and verify the sorted eigenvalues/vectors."""

  # Eigenvalue/vector computation.
  w, v = np.linalg.eig(a)

  # We sort the eigenvalues and eigenvectors (also to match the paper).
  idx = w.argsort()
  w = w[idx]
  v = v[:, idx]

  # From the experiments in 'spectral_decomp.py', we know that for
  # a Hermitian A:
  #   Eigenvalues are real (that's why a Hamiltonian must be Hermitian)
  w = np.real(w)
  return w, v


def compute_u_matrix(a, w, v, t, verify):
  """Compute the various U matrices and exponentiations."""

  # Compute the matrices U an U^2 from A via:
  #   U = exp(i * A * t) (^2)
  #
  # Since U is diagonal:
  u = ops.Operator(np.array([[np.exp(1j * w[0] * t), 0],
                             [0, np.exp(1j * w[1] * t)]]))

  # Both U and U^2 are in the eigenvector basis of A. To convert these
  # operators to the computational basis we apply the similarity
  # transformations:
  u = v @ u @ v.transpose().conj()
  return u


def construct_circuit(b, w, u, c, clock_bits=2):
  """Construct a circuit for the given paramters."""

  qc = circuit.qc('hhl', eager=True)
  breg = qc.reg(1, 0)
  clock = qc.reg(clock_bits, 0)
  anc = qc.reg(1, 0)

  # Initialize 'b' to (0, 1), if appropriate.
  if b[1] == 1:
    qc.x(breg)

  # State Preparation, which is basically phase estimation.
  qc.h(clock)
  u_phase = u
  u_phase_gates = []
  for idx in range(clock_bits):
    qc.ctl_2x2(clock[idx], breg, u_phase)
    u_phase_gates.append(u_phase)
    u_phase = u_phase @ u_phase

  # Inverse QFT. After this, the eigenvalues will be
  # in the clock register.
  qc.inverse_qft(clock, True)

  # From above we know that:
  #   theta = 2 arcsin(1 / lam_j)
  #
  # We need a function that performs the rotation for
  # all lam's that are non-zero. In the verify example the
  # lam's are |1> and |2>:
  #
  #   theta(c) = theta(c_1 c_0) = 2 arcsin(C / c)
  #
  # where c is the value of the clock qubits, c_1 c_0 are c
  # in binary.
  #
  # In the example, we must ensure that this function is correct
  # for the states |01> and |10>, corresponding to the lam's:
  #
  #   theta(1) = theta(01) = 2 arcsin(C=1 / 1) = pi
  #   theta(2) = theta(10) = 2 arcsin(C=1 / 2) = pi/3
  #
  # In general, this theta function must be computed (which is
  # trivial when lam's binary representations don't have matching 1's).
  # For the verified example, the solution is simple as no bits overlap:
  #   theta(c) = theta(c_1 c_0) = pi/3 c_1 + pi c_0
  # So we have to rotate the ancilla via qubit c_1 by pi/3
  # and via qubit c_0 by pi.
  #
  # In general (for 2 lambda's):
  #   if bit 0 is set in the larger lamba, eg., |01> and |11>:
  #
  angle0 = 2 * np.arcsin(c / w[0])
  angle1 = 2 * np.arcsin(c / w[1])
  if int(np.round(w[1])) & 1 == 1:
    angle1 = angle1 - angle0
  qc.cry(clock[0], anc, angle0)
  qc.cry(clock[1], anc, angle1)

  # Measure (and force) ancilla to be |1>.
  _, _ = qc.measure_bit(anc[0], 1, collapse=True)

  # QFT
  qc.qft(clock, True)

  # Uncompute state initialization.
  for idx in range(clock_bits-1, -1, -1):
    qc.ctl_2x2(clock[idx], breg, np.linalg.inv(u_phase_gates[idx]))

  # Move clock bits out of Hadamard basis.
  qc.h(clock)
  qc.psi.dump('Final state')
  return qc


def run_experiment(a, b, verify: bool = False):
  """Run a single instance of HHL for Ax = b."""

  if not a.is_hermitian():
    raise AssertionError('Input A must be Hermitian.')

  # For quantum, initial parameters.
  dim = a.shape[0]

  # pylint: disable=invalid-name
  N = dim**2

  # Compute (and verify) eigenvalue/vectors.
  w, v = compute_sorted_eigenvalues(a, verify)

  # Compute and print the ratio. We will compare the results
  # against this value below.
  ratio = w[1] / w[0]

  # We also know that:
  #   lam_i = (N * w[j] * t) / (2 * np.pi)
  # We want lam_i to be integers, so we compute 't' as:
  #   t = lam[0] / N / w[0] * 2 * np.pi
  t = ratio / N / w[1] * 2 * np.pi

  # With 't' we can now compute the integer eigenvalues:
  lam = [(N * np.real(w[i]) * t / (2 * np.pi)) for i in range(2)]
  print(f'Scaled Lambda\'s are: {lam[0]:.1f}, {lam[1]:.1f}. Ratio: {ratio:.1f}')

  # Compute the U matrices.
  u = compute_u_matrix(a, w, v, t, verify)

  # On to computing the rotations.
  #
  # The factors to |0> and 1> of the ancilla will be:
  #   \sqrt{1 - C^2 / lam_j^2} and C / lam_j
  #
  # C must be smaller than the minimal lam. We set it to the minimum:
  C = np.min(lam)
  print(f'Set C to minimal Eigenvalue: {C:.1f}')

  # Now we have all the values and matrices. Let's construct a circuit.
  qc = construct_circuit(b, lam, u, C, 2)
  check_results(qc, a, b, verify)


def main(argv):
  if len(argv) > 1:
    raise app.UsageError('Too many command-line arguments.')

  print('General HHL Algorithm...')
  print('*** This is WIP ***')

  # Preliminary: Check the rotation mechanism.
  check_rotate_ry(1.2)

  # The numerical 2x2 Hermitian example is from:
  #   "Step-by-Step HHL Algorithm Walkthrough..." by
  #    Morrell, Zaman, Wong
  #
  # Maps to Eigenvalues |01> and |10> interpreted as decimal 1 and 2
  a = ops.Operator(np.array([[1.0, -1/3], [-1/3, 1]]))
  b = ops.Operator(np.array([0, 1]))
  run_experiment(a, b, True)

  # Maps to Eigenvalues |01> and |11> interpreted as decimal 1 and 3
  a = ops.Operator(np.array([[1.0, -1/2], [-1/2, 1]]))
  b = ops.Operator(np.array([0, 1]))
  run_experiment(a, b, False)

  # Maps to Eigenvalues |01> and |10> interpreted as decimal 1/2 and 1/4
  a = ops.Operator(np.array([[1.0, -1/3], [-1/3, 1]]))
  b = ops.Operator(np.array([1, 0]))
  run_experiment(a, b, False)

  # Maps to Eigenvalues |01> and |11> interpreted as decimal 1/2 and 1/3
  a = ops.Operator(np.array([[1.0, -1/2], [-1/2, 1]]))
  b = ops.Operator(np.array([1, 0]))
  run_experiment(a, b, False)


if __name__ == '__main__':
  np.set_printoptions(precision=4)
  app.run(main)
