"""The algorithms the Models tab tests, as factories. Each returns an unfitted classifier with fit(X, y) and
predict_proba(X); missing values are allowed (imputed where the method needs it). Every one is deliberately small and
regularised: a few days of data from a few hundred coins cannot support deep trees or wide networks, and a model that
fits its training data closely only looks good until it trades. Needs scikit-learn, xgboost-cpu and lightgbm (see
requirements-ml.txt); the scanner itself runs without them."""
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.naive_bayes import GaussianNB
from sklearn.neural_network import MLPClassifier


def _imp(indicator=False):
    return SimpleImputer(strategy="median", add_indicator=indicator, keep_empty_features=True)


def logistic():
    return make_pipeline(_imp(True), StandardScaler(), LogisticRegression(C=0.1, class_weight="balanced", max_iter=3000))


def random_forest():
    return make_pipeline(_imp(), RandomForestClassifier(n_estimators=300, max_depth=6, min_samples_leaf=40, max_features="sqrt",
                                                        class_weight="balanced_subsample", n_jobs=-1, random_state=0))


def extra_trees():
    return make_pipeline(_imp(), ExtraTreesClassifier(n_estimators=300, max_depth=6, min_samples_leaf=40, max_features="sqrt",
                                                      class_weight="balanced_subsample", n_jobs=-1, random_state=0))


def gradient_boosting():
    return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=300, l2_regularization=1.0,
                                          min_samples_leaf=40, early_stopping=True, validation_fraction=0.15,
                                          class_weight="balanced", random_state=0)


class _Balanced:
    """Weights the classes equally for libraries that take sample weights rather than a class_weight setting."""

    def __init__(self, model):
        self.model = model

    def fit(self, X, y):
        import numpy as np
        y = np.asarray(y)
        pos = y.mean() if len(y) else 0.5
        w = np.where(y > 0, 0.5 / pos if pos > 0 else 1.0, 0.5 / (1 - pos) if pos < 1 else 1.0)
        self.model.fit(X, y, sample_weight=w)
        return self

    def predict_proba(self, X):
        return self.model.predict_proba(X)


def xgboost():
    from xgboost import XGBClassifier
    return _Balanced(XGBClassifier(n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                                   min_child_weight=10, reg_lambda=1.0, tree_method="hist", n_jobs=4, random_state=0,
                                   eval_metric="logloss", verbosity=0))


def lightgbm():
    from lightgbm import LGBMClassifier
    return LGBMClassifier(n_estimators=300, max_depth=4, num_leaves=15, learning_rate=0.05, min_child_samples=40,
                          subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, class_weight="balanced",
                          random_state=0, verbose=-1)


def knn():
    # uniform weights: with distance weights every training point is its own nearest neighbour at distance zero, so
    # its training scores are its own labels and no threshold set on them means anything
    return make_pipeline(_imp(), StandardScaler(), KNeighborsClassifier(n_neighbors=75, weights="uniform"))


def naive_bayes():
    return make_pipeline(_imp(), GaussianNB())


def mlp():
    return make_pipeline(_imp(True), StandardScaler(),
                         MLPClassifier(hidden_layer_sizes=(32, 16), alpha=1e-3, early_stopping=True, validation_fraction=0.15,
                                       max_iter=300, random_state=0))


# name shown on the page -> (factory, family)
TABULAR = {
    "Logistic regression": logistic, "Random forest": random_forest, "Extra trees": extra_trees,
    "Gradient boosting": gradient_boosting, "XGBoost": xgboost, "LightGBM": lightgbm,
    "k nearest neighbours": knn, "Naive Bayes": naive_bayes, "Neural network (MLP)": mlp,
}
FAMILY = {"Logistic regression": "linear", "Random forest": "tree ensemble", "Extra trees": "tree ensemble",
          "Gradient boosting": "boosted trees", "XGBoost": "boosted trees", "LightGBM": "boosted trees",
          "k nearest neighbours": "instance-based", "Naive Bayes": "probabilistic", "Neural network (MLP)": "neural network",
          "LSTM": "recurrent neural network"}
EXIT = {"Logistic regression": logistic, "Random forest": random_forest, "Gradient boosting": gradient_boosting,
        "LightGBM": lightgbm, "Neural network (MLP)": mlp}


# ---- models of the trade's return rather than of whether it wins: a classifier rewards a 60% chance of +5% as much
#      as a 60% chance of +50%, and memecoin trades that often win small and sometimes lose big can rank well and lose
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor, HistGradientBoostingRegressor


def ridge():
    return make_pipeline(_imp(True), StandardScaler(), Ridge(alpha=30.0))


def random_forest_reg():
    return make_pipeline(_imp(), RandomForestRegressor(n_estimators=300, max_depth=6, min_samples_leaf=60, max_features="sqrt",
                                                       n_jobs=-1, random_state=0))


def gradient_boosting_reg():
    return HistGradientBoostingRegressor(loss="absolute_error", max_depth=3, learning_rate=0.05, max_iter=300,
                                         l2_regularization=1.0, min_samples_leaf=60, early_stopping=True,
                                         validation_fraction=0.15, random_state=0)


def xgboost_reg():
    from xgboost import XGBRegressor
    return XGBRegressor(n_estimators=300, max_depth=3, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                        min_child_weight=20, reg_lambda=1.0, objective="reg:pseudohubererror", huber_slope=10.0, tree_method="hist",
                        n_jobs=4, random_state=0, verbosity=0)


def lightgbm_reg():
    from lightgbm import LGBMRegressor
    return LGBMRegressor(n_estimators=300, max_depth=4, num_leaves=15, learning_rate=0.05, min_child_samples=60,
                         subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, objective="huber",
                         random_state=0, verbose=-1)


REGRESSION = {"Ridge regression": ridge, "Random forest (return)": random_forest_reg,
              "Gradient boosting (return)": gradient_boosting_reg, "XGBoost (return)": xgboost_reg,
              "LightGBM (return)": lightgbm_reg}
FAMILY.update({"Ridge regression": "linear", "Random forest (return)": "tree ensemble",
               "Gradient boosting (return)": "boosted trees", "XGBoost (return)": "boosted trees",
               "LightGBM (return)": "boosted trees"})
