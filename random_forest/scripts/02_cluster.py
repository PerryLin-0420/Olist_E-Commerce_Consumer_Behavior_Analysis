"""Step 02: segment sellers and customers with an unsupervised random forest.

See rf_segment.py for the method. Sellers (~3K) use the full proximity
matrix; customers (~95K) are clustered on a sample and assigned to centroids.

Outputs: outputs/{entity}_clusters.csv, _k_selection.csv, _profile.csv,
_feature_importance.csv; charts/{entity}_cluster_profile.png,
{entity}_feature_importance.png
"""
import pandas as pd

from rf_common import FEATURE_DIR, MIN_LEAF
from rf_segment import run_segmentation

ENTITIES = {
    "seller": {"file": "seller_features.csv", "id": "seller_id", "drop": ["seller_state"],
               "prefix": "S", "label": "Seller"},
    "customer": {"file": "customer_features.csv", "id": "customer_unique_id",
                 "drop": ["customer_state"], "prefix": "C", "label": "Customer"},
}


def load(entity: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg = ENTITIES[entity]
    df = pd.read_csv(FEATURE_DIR / cfg["file"])
    X = df.drop(columns=[cfg["id"], *cfg["drop"]])
    return df[[cfg["id"]]], X.fillna(X.median())


def main() -> None:
    for entity, cfg in ENTITIES.items():
        ids, X = load(entity)
        run_segmentation(entity, cfg["label"], ids, X, cfg["prefix"], MIN_LEAF[entity])


if __name__ == "__main__":
    main()
