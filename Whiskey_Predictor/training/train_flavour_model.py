import pandas as pd
import pickle
import os

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression

# =====================================================
# PATHS
# =====================================================
DATA_PATH = "../data/raw/Final_output.xlsx"
BASE_MODEL_PATH = "../models"

os.makedirs(BASE_MODEL_PATH, exist_ok=True)

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
# FLAVOUR TARGET COLUMNS
# =====================================================
FLAVOUR_TARGETS = {
    "Cereal/Grainy": "Cereal/Grainy",
    "Fruity_&_Floral": "Fruity_&_Floral",
    "Fermented": "Fermented",
    "Husky": "Husky",
    "Starchy": "Starchy",
    "Cooked": "Cooked",
    "Acidic/Solvent": "Acidic/Solvent"
}

# =====================================================
# FINAL FEATURES AFTER ANOVA → VIF (SOURCE OF TRUTH)
# =====================================================
FINAL_FEATURES = {
    "cereal_grainy": [
        "Wort initial gravity (25L Vessel)",
        "SCREENING - below 2.2mm sieve ",
        "Final Wash temperature_Fermentated Wash",
        "Yeast Storage Temperature, deg C",
        "Final Wash turbidity",
        "Spirit Still temperature - Mean_Spirit_B (Max)",
        "Wort receiver temperature",
        "Low wine alcohol % obtained_Spirit_A",
        "Wort final gravity (25L Vessel)"
    ],

    "fruity_and_floral": [
        "Mashing temperature",
        "Temperature in Mashtun (Spezyme alpha NK)",
        "Temperature in Mash-tun (Diazyme TGA)",
        "Strength in PL_merge2",
        "Set-up Wort pH",
        "Wash distillation Rate - Mean",
        "Final wash pH",
        "Set-up wort gravity",
        "1st wort turbidity_Wort",
        "Low wine turbidity Mean_Spirit_A"
    ],

    "fermented": [
        "Set-up Wort pH",
        "Wort final gravity (700L Vessel)",
        "Malt foreign matter",
        "Low wine alcohol % obtained_Spirit_A",
        "Malt Hot water extract on dry weight basis (min)",
        "Spirit distillation Rate - Mean_Spirit_B"
    ],

    "husky": [
        "Spirit Still temperature - Mean_Spirit_B (Max)",
        "Sparging water temperature",
        "Wash condenser temperature(Max) - Mean",
        "Weak wort output temperature",
        "Grist Ratio on Milling - 1 Course",
        "% Shelf life available Proteinase T ",
        "Wash Still temperature(Max) - Mean"
    ],

    "starchy": [
        "Strength in PL_merge2",
        "Average ABV in FMS_Spirit_A",
        "Draff loss",
        "SCREENING - below 2.2mm sieve ",
        "Recovery PL/Ton of Malt",
        "Mashing temperature",
        "Set-up Wort pH",
        "Wort final gravity (700L Vessel)"
    ],

    "cooked": [
        "% Shelf life available Optimash TBG",
        "Wash Still temperature(Max) - Mean",
        "Time of addition of Enzyme (Proteinase T)",
        "Spirit condenser temperature - Mean_Spirit_B",
        "Wort initial pH (2500L Vessel)",
        "pH_Process Water"
    ],

    "acidic_solvent": [
        "Strength in PL_merge2",
        "Average ABV in FMS_Spirit_A",
        "Wort final gravity (700L Vessel)",
        "Mashing temperature",
        "Low wine turbidity Mean_Spirit_B",
        "Wort initial gravity 700 L "
    ]
}

# =====================================================
# TRAIN PER FLAVOUR
# =====================================================
for flavour, target_col in FLAVOUR_TARGETS.items():

    print(f"\n🚀 Training model for {flavour}")

    features = FINAL_FEATURES[flavour]

    # Validate columns
    missing = [f for f in features if f not in df.columns]
    if missing:
        raise ValueError(f"Missing features for {flavour}: {missing}")

    X = df[features]
    y = df[target_col]

    # Train split
    X_train, _, y_train, _ = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # =====================================================
    # FEATURE RANGES (FOR UI)
    # =====================================================
    feature_ranges = {
        col: (
            float(X_train[col].quantile(0.05)),
            float(X_train[col].quantile(0.95))
        )
        for col in features
    }

    # =====================================================
    # SCALE → PCA → MODEL
    # =====================================================
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X_train)

    pca = PCA(n_components=0.95, random_state=42)
    X_pca = pca.fit_transform(X_scaled)

    model = LogisticRegression(max_iter=1000)
    model.fit(X_pca, y_train)

    # =====================================================
    # SAVE ARTIFACTS
    # =====================================================
    save_path = os.path.join(
        BASE_MODEL_PATH,
        flavour.lower().replace("/", "_").replace("&", "and")
    )
    os.makedirs(save_path, exist_ok=True)

    pickle.dump(scaler, open(f"{save_path}/scaler.pkl", "wb"))
    pickle.dump(pca, open(f"{save_path}/pca.pkl", "wb"))
    pickle.dump(model, open(f"{save_path}/model.pkl", "wb"))
    pickle.dump(features, open(f"{save_path}/features.pkl", "wb"))
    pickle.dump(feature_ranges, open(f"{save_path}/feature_ranges.pkl", "wb"))

    print(f"✅ Saved model + metadata for {flavour}")

print("\n🎉 All flavour models trained successfully")
