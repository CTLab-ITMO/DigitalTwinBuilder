import numpy as np


def sliding_window_sequences(X, index, y=None, window_size=100, step_size=1, target_size=1):
    if y is None:
        y = X.copy()

    windows = list()
    targets = list()
    indices = list()

    length = len(X)
    # `X[i : i + window_size]` ends at index `i + window_size - 1`, so the point
    # immediately after the window is `end = i + window_size`. The old bounds
    # (`range(0, length - window_size - 1)`, `y[end + 1]`) skipped that point and
    # aimed one further ahead, dropping the last usable window and leaving a
    # one-row gap between every window and its target. `target_size` was also
    # accepted and ignored; it now sets how many rows past the window's end the
    # target sits (`target_size=1` is the next row), and it is that many rows
    # that decide where windows have to stop.
    last_start = length - window_size - target_size
    for i in range(0, last_start + 1, step_size):
        start = i
        end = i + window_size
        windows.append(X[start: end])
        targets.append(y[end + target_size - 1])
        indices.append(index[end + target_size - 1])

    return np.array(windows, dtype=np.float32), np.array(targets, dtype=np.float32), np.array(indices)
