"""Shared paths and settings for the random forest segmentation pipeline."""
import sys
import warnings
from pathlib import Path

# joblib on Python 3.14 emits this once per tree; it does not affect results
warnings.filterwarnings("ignore", message=".*sklearn.utils.parallel.delayed.*")

RF_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = RF_DIR.parent
FEATURE_DIR = RF_DIR / "features"
OUTPUT_DIR = RF_DIR / "outputs"
CHART_DIR = RF_DIR / "charts"

# Reuse the EDA chart style and DB helpers
sys.path.insert(0, str(PROJECT_DIR / "EDA" / "scipts"))
import eda_utils  # noqa: E402

eda_utils.CHART_DIR = CHART_DIR
eda_utils.OUTPUT_DIR = OUTPUT_DIR

N_TREES = 50
RANDOM_STATE = 42
K_RANGE = range(3, 11)            # candidate cluster counts
MIN_CLUSTER_SHARE = 0.01          # a valid k keeps every cluster >= 1% of rows
CUSTOMER_SAMPLE = 5000            # customers clustered hierarchically, rest assigned
# min_samples_leaf of the unsupervised forest; chosen so the silhouette peaks
# inside K_RANGE instead of at its edge (see outputs/*_k_selection.csv)
MIN_LEAF = {"seller": 5, "customer": 200}
STABILITY_SEED = 7               # second seed for the stability (ARI) check

# Business rule: a customer re-uses the platform (any seller) when they purchase on
# more than one date, so "active" = purchases on >= 2 distinct dates
ACTIVE_MIN_PURCHASE_DAYS = 2

# Categories with their own share feature (top by revenue); the rest go to "other"
N_TOP_CATEGORIES = 12
