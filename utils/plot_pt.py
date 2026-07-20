import numpy as np
import matplotlib.pyplot as plt
import os

def plot_pt_distributions(normalized_probs: np.ndarray, n_qubits: int, actual_cnots: int, shots: int, backend: str, out_dir: str):
    """绘制真实量子芯片数据的 PT 分布，并输出 PNG 和 SVG"""
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.set_facecolor('#050508')
    fig.patch.set_facecolor('#050508')

    counts_hist, bins, patches = ax.hist(
        normalized_probs, 
        bins=min(50, max(10, len(normalized_probs)//10)), 
        density=True, 
        alpha=0.7, 
        color='#8B5CF6', 
        label=f'Real Hardware RCS ({backend})'
    )
    
    x = np.linspace(0, max(normalized_probs) if len(normalized_probs) > 0 else 5, 200)
    y = np.exp(-x)
    ax.plot(x, y, color='#45F3FF', linestyle='--', lw=2.5, label='Theoretical PT ($e^{-x}$)')
    
    ax.set_yscale('log')
    ax.set_ylim(bottom=1e-4)
    
    ax.set_xlabel(r'Normalized Probability ($N \cdot p$)', fontsize=12, color='white')
    ax.set_ylabel('Probability Density (log scale)', fontsize=12, color='white')
    ax.set_title(f'Porter-Thomas Distribution on Real Hardware\n({n_qubits} qubits, ~{actual_cnots} CNOTs, {shots} shots)', fontsize=14, color='white')
    ax.legend(facecolor='#14141c', edgecolor='#334155', labelcolor='white')
    ax.grid(True, alpha=0.3, which="both", ls="--", color='#334155')
    
    ax.tick_params(colors='white')
    for spine in ax.spines.values():
        spine.set_color('#334155')
        
    plt.tight_layout()
    
    png_path = os.path.join(out_dir, "pt_plot.png")
    svg_path = os.path.join(out_dir, "pt_plot.svg")
    
    plt.savefig(png_path, dpi=300, transparent=True)
    plt.savefig(svg_path, format='svg', transparent=True)
    plt.close(fig)
    return png_path, svg_path
