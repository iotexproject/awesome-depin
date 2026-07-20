import numpy as np
import pandas as pd
from pathlib import Path
import os

def generate_ideal_pt(n_states: int, seed: int = 42) -> np.ndarray:
    """Generate an ideal Porter-Thomas distribution of size n_states."""
    np.random.seed(seed)
    # PT distribution corresponds to exponential distribution Exp(1) for N*p
    # So we sample from Exp(1) and normalize
    samples = np.random.exponential(scale=1.0, size=n_states)
    probs = samples / np.sum(samples)
    return probs * 100  # Convert to percentage to match original format

def process_all_files():
    data_dir = Path("data")
    if not data_dir.exists():
        print(f"Data directory {data_dir} not found.")
        return

    csv_files = list(data_dir.glob("task_*_result.csv"))
    if not csv_files:
        print("No task CSV files found.")
        return

    for i, csv_file in enumerate(csv_files):
        print(f"Processing {csv_file.name}...")
        df = pd.read_csv(csv_file)
        states = df.iloc[:, 0].values.astype(str)
        n_states = len(states)
        
        # Generate ideal PT probabilities
        ideal_probs = generate_ideal_pt(n_states, seed=2026+i)
        
        # Create a new dataframe
        ideal_df = pd.DataFrame({
            "States": states,
            " Raw probabilities(%)": ideal_probs
        })
        
        # Save as a new ideal PT file
        output_name = csv_file.name.replace("task_", "ideal_pt_")
        output_path = data_dir / output_name
        ideal_df.to_csv(output_path, index=False)
        print(f"  -> Saved ideal PT distribution to {output_path.name}")

if __name__ == "__main__":
    process_all_files()