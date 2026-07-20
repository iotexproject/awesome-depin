import numpy as np

f_xeb_sycamore = 0.00224
cv_sycamore = np.sqrt(f_xeb_sycamore)
print(f"Calculated CV for Sycamore (53 qubits): {cv_sycamore:.4f}")

# The user's image shows:
# CV ≈ 0.047 (Noise)
print(f"Expected CV from user image: 0.047")
print(f"Match? {np.isclose(cv_sycamore, 0.047, atol=0.001)}")

# Heavy Tail ratio calculation
# P_m(x) = F_XEB * Exp(-x) + (1-F_XEB) * delta(x-1)
# Heavy tail ratio is P(x > 2). 
# For ideal PT, P(x > 2) = exp(-2) ≈ 0.135
# For measured distribution, it's just scaled by F_XEB:
heavy_tail_sycamore = f_xeb_sycamore * np.exp(-2)
print(f"Calculated Heavy Tail for Sycamore: {heavy_tail_sycamore:.5f}")

# But wait, the user's table says KS ≈ 0.49 (Noise) and Heavy Tail ≈ 0.50 (Noise)?
# Actually, the columns are:
# Qubits: 53
# Layers/Depth: 20
# 2-Qubit Gates: 430
# Sampling Shots: 1000000
# CV: ≈ 0.047 (Noise)
# KS Statistic: ≈ 0.49 (Noise)
# Heavy Tail Ratio: N/A
# F_XEB (Shape Proxy): ≈ 0.50 (Noise) ??? Wait, let me look closer at the image.
