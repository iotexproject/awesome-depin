import numpy as np
import scipy.stats as stats
import matplotlib.pyplot as plt
import os
import json

class QuantumTransportAgent:
    """
    Quantum Transport Agent (Mapping II & III):
    Uses 1D Monotone Optimal Transport (Quantile Transport)
    to map Porter-Thomas (Exponential) source samples to
    prescribed target distributions (Risk and Exploration).
    """
    
    def __init__(self):
        pass
    
    def pt_ot_mapping(self, source_samples: np.ndarray, target_ppf) -> np.ndarray:
        """
        T(y) = G^{-1}(F_{PT}(y))
        where G^{-1} is target_ppf, and F_{PT} is the empirical CDF of source_samples.
        """
        ranks = stats.rankdata(source_samples, method='average')
        n_samples = len(source_samples)
        # Avoid exactly 0.0 or 1.0
        f_pt = (ranks - 0.5) / n_samples
        mapped_samples = target_ppf(f_pt)
        return mapped_samples

    def pt_ot_multidimensional_mapping(self, source_samples_nd: np.ndarray, target_ppfs: list) -> np.ndarray:
        """
        Extension for Multidimensional Optimal Transport with Copula structure preservation.
        T_d(Y) = (G_1^{-1}(C_1(F_{PT}(Y_1))), ..., G_d^{-1}(C_d(F_{PT}(Y_d))))
        source_samples_nd: shape (N, D)
        target_ppfs: list of D ppf functions
        """
        N, D = source_samples_nd.shape
        mapped_nd = np.zeros_like(source_samples_nd)
        
        for d in range(D):
            # 1D Empirical CDF (F_PT) for dimension d
            ranks = stats.rankdata(source_samples_nd[:, d], method='average')
            f_pt = (ranks - 0.5) / N
            # Apply marginal target PPF
            mapped_nd[:, d] = target_ppfs[d](f_pt)
            
        return mapped_nd

class MixtureDistribution:
    """
    Helper class to create a mixture of two distributions:
    H = (1 - rho) * dist1 + rho * dist2
    """
    def __init__(self, rho, dist1, dist2, scale=1.0):
        self.rho = rho
        self.dist1 = dist1
        self.dist2 = dist2
        self.scale = scale

    def cdf(self, x):
        x_scaled = x / self.scale
        return (1 - self.rho) * self.dist1.cdf(x_scaled) + self.rho * self.dist2.cdf(x_scaled)

    def ppf(self, q):
        from scipy.optimize import root_scalar
        res = np.zeros_like(q)
        for i, q_val in enumerate(np.atleast_1d(q)):
            if q_val <= 0:
                res[i] = 0.0
            elif q_val >= 1:
                res[i] = self.scale
            else:
                f = lambda x: self.cdf(x) - q_val
                try:
                    sol = root_scalar(f, bracket=[0, self.scale], method='brentq')
                    res[i] = sol.root
                except:
                    res[i] = 0.0
        return res if np.isscalar(q) else res

_agent_instance = QuantumTransportAgent()

def pt_ot_mapping(source_samples, target_ppf):
    return _agent_instance.pt_ot_mapping(source_samples, target_ppf)
