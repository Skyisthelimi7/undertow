"""A small LSTM in numpy: one recurrent layer over a short sequence of scans, then a logistic output (task "cls",
whether the trade wins) or a linear one (task "reg", the trade's return, on squared error). Trained by
backpropagation through time with Adam, L2 weight decay and early stopping on a later slice of the data, so it needs
nothing beyond numpy and its weights can be saved as plain lists.

Shapes: X (batch, steps, features) with missing readings already filled; M (batch, steps) is 1 for a real reading and
0 for padding, and a padded step leaves the state unchanged."""
import json
import numpy as np


def _sig(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


class LSTM:
    def __init__(self, n_in, hidden=16, l2=1e-3, lr=5e-3, epochs=40, batch=256, patience=5, seed=0, task="cls"):
        self.n_in, self.h, self.l2, self.lr, self.epochs, self.batch, self.patience = n_in, hidden, l2, lr, epochs, batch, patience
        self.task, self.ymu, self.ysd = task, 0.0, 1.0
        rng = np.random.default_rng(seed)
        H = hidden
        self.p = {"Wx": rng.normal(0, 1 / np.sqrt(n_in), (n_in, 4 * H)), "Wh": rng.normal(0, 1 / np.sqrt(H), (H, 4 * H)),
                  "b": np.zeros(4 * H), "w": rng.normal(0, 1 / np.sqrt(H), H), "c": np.zeros(1)}
        self.p["b"][H:2 * H] = 1.0                  # forget gate starts open, so early steps are remembered
        self.mu = self.sd = None
        self.history = []

    # ---------------------------------------------------------------- forward and backward
    def _forward(self, X, M, keep=False):
        B, T, _ = X.shape
        H = self.h
        h, c = np.zeros((B, H)), np.zeros((B, H))
        cache = []
        for t in range(T):
            x, m = X[:, t, :], M[:, t][:, None]
            z = x @ self.p["Wx"] + h @ self.p["Wh"] + self.p["b"]
            i, f, o, g = _sig(z[:, :H]), _sig(z[:, H:2 * H]), _sig(z[:, 2 * H:3 * H]), np.tanh(z[:, 3 * H:])
            c_new = f * c + i * g
            tc = np.tanh(c_new)
            h_new = o * tc
            if keep:
                cache.append((x, m, h, c, i, f, o, g, tc))
            h = m * h_new + (1 - m) * h
            c = m * c_new + (1 - m) * c
        logit = h @ self.p["w"] + self.p["c"][0]
        return logit, h, cache

    def _loss_grad(self, X, M, y, wt):
        B = X.shape[0]
        H = self.h
        logit, hT, cache = self._forward(X, M, keep=True)
        if getattr(self, "task", "cls") == "reg":          # half the squared error of the scaled return
            err = logit - y
            loss = 0.5 * np.sum(wt * err ** 2) / B
            dlogit = wt * err / B
        else:
            p = _sig(logit)
            eps = 1e-9
            loss = -np.sum(wt * (y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps))) / B
            dlogit = wt * (p - y) / B
        loss += 0.5 * self.l2 * sum(np.sum(self.p[k] ** 2) for k in ("Wx", "Wh", "w"))
        g = {k: np.zeros_like(v) for k, v in self.p.items()}
        g["w"] = hT.T @ dlogit
        g["c"] = np.array([dlogit.sum()])
        dh = dlogit[:, None] * self.p["w"][None, :]
        dc = np.zeros((B, H))
        for x, m, h_prev, c_prev, i, f, o, gg, tc in reversed(cache):
            dh_new, dh_skip = m * dh, (1 - m) * dh
            dc_in, dc_skip = m * dc, (1 - m) * dc
            do = dh_new * tc
            dcn = dc_in + dh_new * o * (1 - tc ** 2)
            df, di, dg = dcn * c_prev, dcn * gg, dcn * i
            dz = np.concatenate([di * i * (1 - i), df * f * (1 - f), do * o * (1 - o), dg * (1 - gg ** 2)], axis=1)
            g["Wx"] += x.T @ dz
            g["Wh"] += h_prev.T @ dz
            g["b"] += dz.sum(axis=0)
            dh = dz @ self.p["Wh"].T + dh_skip
            dc = dcn * f + dc_skip
        for k in ("Wx", "Wh", "w"):
            g[k] += self.l2 * self.p[k]
        return loss, g

    # ---------------------------------------------------------------- training
    def _scale(self, X):
        return np.nan_to_num((X - self.mu) / self.sd, nan=0.0, posinf=0.0, neginf=0.0)

    def fit(self, X, M, y, val=0.15, seed=0):
        """X (n, steps, features) in time order; the last `val` share is held out for early stopping."""
        X, M, y = np.asarray(X, float), np.asarray(M, float), np.asarray(y, float)
        flat = X[M > 0]
        self.mu = np.nanmean(flat, axis=0) if len(flat) else np.zeros(self.n_in)
        sd = np.nanstd(flat, axis=0) if len(flat) else np.ones(self.n_in)
        self.mu, self.sd = np.nan_to_num(self.mu), np.where(np.nan_to_num(sd) > 1e-9, np.nan_to_num(sd), 1.0)
        Xs = self._scale(X) * M[:, :, None]
        n = len(y)
        cut = max(1, int(n * (1 - val)))
        if getattr(self, "task", "cls") == "reg":          # the return, scaled on the training slice; every sample alike
            self.ymu = float(np.mean(y[:cut]))
            self.ysd = float(np.std(y[:cut])) or 1.0
            y = (y - self.ymu) / self.ysd
            weight = lambda yy: np.ones_like(yy)
        Xt, Mt, yt, Xv, Mv, yv = Xs[:cut], M[:cut], y[:cut], Xs[cut:], M[cut:], y[cut:]
        if getattr(self, "task", "cls") != "reg":          # the classes weighted equally
            pos = yt.mean() if len(yt) else 0.5
            wpos, wneg = (0.5 / pos if 0 < pos < 1 else 1.0), (0.5 / (1 - pos) if 0 < pos < 1 else 1.0)
            weight = lambda yy: np.where(yy > 0.5, wpos, wneg)
        rng = np.random.default_rng(seed)
        mom = {k: np.zeros_like(v) for k, v in self.p.items()}
        vel = {k: np.zeros_like(v) for k, v in self.p.items()}
        best, best_p, bad, step = np.inf, None, 0, 0
        for ep in range(self.epochs):
            order = rng.permutation(len(yt))
            for s in range(0, len(order), self.batch):
                idx = order[s:s + self.batch]
                _loss, g = self._loss_grad(Xt[idx], Mt[idx], yt[idx], weight(yt[idx]))
                step += 1
                for k in self.p:
                    mom[k] = 0.9 * mom[k] + 0.1 * g[k]
                    vel[k] = 0.999 * vel[k] + 0.001 * g[k] ** 2
                    self.p[k] -= self.lr * (mom[k] / (1 - 0.9 ** step)) / (np.sqrt(vel[k] / (1 - 0.999 ** step)) + 1e-8)
            vl = self._loss_grad(Xv, Mv, yv, weight(yv))[0] if len(yv) else 0.0
            self.history.append(round(float(vl), 5))
            if vl < best - 1e-5:
                best, best_p, bad = vl, {k: v.copy() for k, v in self.p.items()}, 0
            else:
                bad += 1
                if bad >= self.patience:
                    break
        if best_p is not None:
            self.p = best_p
        return self

    def predict_proba(self, X, M):
        Xs = self._scale(np.asarray(X, float)) * np.asarray(M, float)[:, :, None]
        return _sig(self._forward(Xs, np.asarray(M, float))[0])

    def predict(self, X, M):
        """The predicted return (task "reg"), in the units it was trained on."""
        Xs = self._scale(np.asarray(X, float)) * np.asarray(M, float)[:, :, None]
        return self._forward(Xs, np.asarray(M, float))[0] * getattr(self, "ysd", 1.0) + getattr(self, "ymu", 0.0)

    # ---------------------------------------------------------------- saving
    def to_dict(self):
        return {"n_in": self.n_in, "h": self.h, "p": {k: v.tolist() for k, v in self.p.items()},
                "mu": self.mu.tolist(), "sd": self.sd.tolist(), "history": self.history,
                "task": getattr(self, "task", "cls"), "ymu": getattr(self, "ymu", 0.0), "ysd": getattr(self, "ysd", 1.0)}

    @classmethod
    def from_dict(cls, d):
        m = cls(d["n_in"], d["h"], task=d.get("task", "cls"))
        m.p = {k: np.asarray(v, float) for k, v in d["p"].items()}
        m.mu, m.sd, m.history = np.asarray(d["mu"], float), np.asarray(d["sd"], float), d.get("history", [])
        m.ymu, m.ysd = d.get("ymu", 0.0), d.get("ysd", 1.0)
        return m

    def dumps(self):
        return json.dumps(self.to_dict(), separators=(",", ":"))
