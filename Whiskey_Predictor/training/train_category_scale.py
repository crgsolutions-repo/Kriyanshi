import pandas as pd
import pickle
import os
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC
from sklearn.model_selection import train_test_split

# =====================================================
# PATHS
# =====================================================
DATA_PATH = "../data/raw/Final_output.xlsx"
MODEL_DIR = "../models/Category_Scale"
os.makedirs(MODEL_DIR, exist_ok=True)

FLAVOUR_MODELS_DIR = "../models"

# =====================================================
# LOAD DATA
# =====================================================
df = pd.read_excel(DATA_PATH)

# =====================================================
# HANDLE MISSING VALUES (NUMERIC ONLY)
# =====================================================
numeric_cols = df.select_dtypes(include="number").columns
df[numeric_cols] = df[numeric_cols].fillna(df[numeric_cols].mean())

# =====================================================
# TARGET
# =====================================================
y = df["Category_Binary"]

# =====================================================
# UNION OF ALL FEATURES FROM FLAVOUR MODELS
# =====================================================
all_features = set()
for folder in os.listdir(FLAVOUR_MODELS_DIR):
    folder_path = os.path.join(FLAVOUR_MODELS_DIR, folder)
    if os.path.isdir(folder_path) and folder != "Category_Scale":
        features_file = os.path.join(folder_path, "features.pkl")
        if os.path.exists(features_file):
            features = pickle.load(open(features_file, "rb"))
            all_features.update(features)

all_features = list(all_features)

# Check for missing columns
missing = [f for f in all_features if f not in df.columns]
if missing:
    raise ValueError(f"Missing features in the dataset: {missing}")

# =====================================================
# SELECT FEATURES FROM DATA
# =====================================================
X = df[all_features]

# =====================================================
# SAVE FEATURE RANGES (FOR STREAMLIT UI)
# =====================================================
feature_ranges = {
    col: (float(X[col].quantile(0.05)), float(X[col].quantile(0.95)))
    for col in X.columns
}

# =====================================================
# TRAIN SPLIT
# =====================================================
X_train, _, y_train, _ = train_test_split(
    X, y, test_size=0.2, random_state=42, stratify=y
)

# =====================================================
# SCALE + MODEL
# =====================================================
scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train)

model = LinearSVC(max_iter=5000)
model.fit(X_train_s, y_train)

# =====================================================
# SAVE PICKLES
# =====================================================
pickle.dump(scaler, open(f"{MODEL_DIR}/scaler.pkl", "wb"))
pickle.dump(model, open(f"{MODEL_DIR}/model.pkl", "wb"))
pickle.dump(all_features, open(f"{MODEL_DIR}/features.pkl", "wb"))
pickle.dump(feature_ranges, open(f"{MODEL_DIR}/feature_ranges.pkl", "wb"))

print(f"✅ Category_Scale model saved successfully with {len(all_features)} features")
