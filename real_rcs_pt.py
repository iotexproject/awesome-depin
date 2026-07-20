import numpy as np
import matplotlib.pyplot as plt
import os
from quafu import QuantumCircuit
from quafu_showtime import bootstrap
from collections import defaultdict

def build_random_circuit(n_qubits: int, depth: int, seed: int = 42) -> QuantumCircuit:
    """
    构建一个达到 Porter-Thomas (PT) 分布的随机量子电路
    控制 CNOT 数量在 200 以内 (Baihua 编译限制)
    """
    np.random.seed(seed)
    qc = QuantumCircuit(n_qubits, n_qubits)
    
    # 初始层：全部施加 H 门，将状态置于全叠加态
    for q in range(n_qubits):
        qc.h(q)
        
    gates = ['rx', 'ry', 'rz']
    cnot_count = 0
    max_cnots = 500 # 按照用户的硬性限制，正好卡在 200
    
    for d in range(depth):
        # 1. 随机单比特门层
        for q in range(n_qubits):
            angle = np.random.uniform(0, 2 * np.pi)
            gate_type = np.random.choice(gates)
            if gate_type == 'rx':
                qc.rx(q, angle)
            elif gate_type == 'ry':
                qc.ry(q, angle)
            else:
                qc.rz(q, angle)
                
        # 2. 纠缠层 (1D 近邻纠缠)
        offset = d % 2
        for q in range(offset, n_qubits - 1, 2):
            if cnot_count >= max_cnots:
                break
            qc.cnot(q, q + 1)
            cnot_count += 1
            
        if cnot_count >= max_cnots:
            print(f"[!] 在深度 {d} 时已达到最大 CNOT 数量限制 ({max_cnots})。")
            break

    # 测量所有量子比特
    qc.measure(list(range(n_qubits)), list(range(n_qubits)))
    return qc, cnot_count

def run_real_hardware_pt():
    # 为了在真机上获得最接近 PT 分布的结果，我们需要平衡两个矛盾：
    # 1. 深度必须足够深，才能让态完全纠缠（Scrambling），达到 PT 分布。
    # 2. 深度不能太深，否则真机的退夸父和门误差会把分布彻底抹平成均匀白噪声（完全偏离 PT）。
    #
    # 优化策略：
    # 减少比特数，这样达到全纠缠所需的深度会变浅（depth ~ n_qubits）。
    # 浅深度意味着更少的错误积累，从而更接近理想的 PT 分布，而不是退化成纯噪声。
    #15+28是Baihua的极限
    n_qubits = 15   
    depth = 28    
    shots = 100000 
    
    print(f"[*] 正在构建 {n_qubits} 比特，期望深度 {depth} 的随机量子电路...")
    qc, actual_cnots = build_random_circuit(n_qubits, depth, seed=2026)
    print(f"[*] 实际生成的 CNOT 门数量: {actual_cnots}")
    
    # print("[*] 正在将量子电路图绘制为单行图片 (可能需要几秒钟)...")
    # fig, ax = plt.subplots(figsize=(65, 8)) # 使用极宽的比例强制单行显示
    # qc.plot_circuit(ax=ax, title=f"Real RCS Circuit (n={n_qubits}, depth={depth}, cnots={actual_cnots})")
    # circuit_img_path = "real_rcs_circuit_1line.png"
    # plt.savefig(circuit_img_path, dpi=150, bbox_inches='tight')
    # plt.close(fig)
    # print(f"[+] 电路图已保存至: {circuit_img_path}")
    
    token = os.environ.get("QUAFU_TOKEN")
    if not token:
        raise ValueError("QUAFU_TOKEN environment variable is required.")
    backend = "Baihua" # 使用夸父百花芯片
    
    print(f"[*] 正在提交任务到真实的量子芯片 {backend} ...")
    print(f"[*] 采样次数 (shots): {shots}")
    
    task = bootstrap(token, backend, shots)
    
    try:
        result = task.send(qc, name="real_hardware_pt", wait=True)
    except Exception as e:
        print(f"[!] 任务提交或运行失败: {e}")
        return

    counts = result.counts
    
    # 将字典形式的 counts 转换为概率数组
    N = 2 ** n_qubits
    probs_dict = defaultdict(float)
    
    for bitstring, count in counts.items():
        # 考虑到硬件可能返回各种噪声，只统计合法的 bitstring
        probs_dict[bitstring] = count / shots
    # 修改后的统计逻辑
    # probs = np.zeros(N) # 初始化一个全 0 的数组
    # for bitstring, count in counts.items():
    #       idx = int(bitstring, 2) # 将 '01011...' 转为整数索引
    #       probs[idx] = count / shots
    # normalized_probs = N * probs
        
    # 我们只关心非零的概率来进行统计，这反映了真实的采样情况
    probs = np.array(list(probs_dict.values()))
    
    # 归一化概率: x = N * p
    normalized_probs = N * probs
    
    print(f"[*] 希尔伯特空间维度 N = {N}")
    print("[*] 正在绘制真实的 Porter-Thomas (PT) 分布图...")
    
    # 开始绘图
    plt.figure(figsize=(10, 6))
    
    # 1. 绘制真实机器的归一化概率分布直方图
    # 由于 N 变小了 (N=64)，我们减少 bins 的数量，以免每个 bin 里的数据点太少而出现锯齿
    counts_hist, bins, patches = plt.hist(
        normalized_probs, 
        bins=25, 
        density=True, 
        alpha=0.7, 
        color='#ff59a7', 
        label=f'Real Hardware RCS ({backend})'
    )
    
    # 2. 绘制理论的 PT 分布曲线 Pr(Np) = e^(-Np)
    x = np.linspace(0, max(normalized_probs) if len(normalized_probs) > 0 else 5, 200)
    y = np.exp(-x)
    plt.plot(x, y, 'b--', lw=2.5, label='Theoretical PT ($e^{-x}$)')
    
    # 设置对数坐标轴
    plt.yscale('log')
    plt.ylim(bottom=1e-4) # 限制下界让图像更美观
    
    # 装饰图表
    plt.xlabel(r'Normalized Probability ($N \cdot p$)', fontsize=12)
    plt.ylabel('Probability Density (log scale)', fontsize=12)
    plt.title(f'Porter-Thomas Distribution on Real Hardware\n({n_qubits} qubits, ~{actual_cnots} CNOTs, {shots} shots)', fontsize=14)
    plt.legend(fontsize=11)
    plt.grid(True, alpha=0.3, which="both", ls="--")
    
    # 保存图像
    output_file = 'real_hardware_pt.png'
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"[+] 完成！分布图已保存至: {output_file}")
    print("[+] 。")

if __name__ == "__main__":
    run_real_hardware_pt()