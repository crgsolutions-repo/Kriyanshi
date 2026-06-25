import streamlit as st
import pickle
import numpy as np
import pandas as pd
import os
from collections import defaultdict

# =====================================================
# PAGE CONFIG
# =====================================================
st.set_page_config(page_title="Whiskey Flavour Predictor", layout="wide")
st.title("🥃 Whiskey Flavour Predictor")

# =====================================================
# PATHS
# =====================================================
APP_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(APP_DIR, "models")

# =====================================================
# FLAVOUR THRESHOLDS & TRAIN/TEST VALUES
# =====================================================
MODEL_STATS = {
    "cereal_grainy": {"threshold": 0.7, "train": 1.0, "test": 0.88},
    "fruity_and_floral": {"threshold": 0.5, "train": 0.93, "test": 0.94},
    "fermented": {"threshold": 0.5, "train": 0.93, "test": 0.94},
    "husky": {"threshold": 0.5, "train": 0.8125, "test": 0.80},
    "starchy": {"threshold": 0.4, "train": 0.68, "test": 0.69},
    "cooked": {"threshold": 0.3, "train": 0.43, "test": 0.44},
    "acidic_solvent": {"threshold": 0.5, "train": 0.5, "test": 0.5},
    "category_scale": {"threshold": 0.76, "train": 0.70, "test": 0.67}
}

# =====================================================
# EMOJI MAP
# =====================================================
EMOJI_MAP = {
    "cereal_grainy": "🟤",
    "fruity_and_floral": "🌸",
    "fermented": "🍺",
    "husky": "🌾",
    "starchy": "🥔",
    "cooked": "🍳",
    "acidic_solvent": "🧪",
    "category_scale": "⚖️"
}

# =====================================================
# LOAD MODELS
# =====================================================
@st.cache_resource
def load_all_models():
    models_data = {}
    all_feature_ranges = defaultdict(list)

    if not os.path.exists(MODEL_DIR):
        st.error(f"Model directory not found: {MODEL_DIR}")
        return {}, {}

    for folder in os.listdir(MODEL_DIR):
        path = os.path.join(MODEL_DIR, folder)
        if not os.path.isdir(path):
            continue

        key = folder.lower()
        try:
            scaler = pickle.load(open(os.path.join(path, "scaler.pkl"), "rb"))
            model = pickle.load(open(os.path.join(path, "model.pkl"), "rb"))
            features = pickle.load(open(os.path.join(path, "features.pkl"), "rb"))
            feature_ranges = pickle.load(open(os.path.join(path, "feature_ranges.pkl"), "rb"))
            pca_path = os.path.join(path, "pca.pkl")
            pca = pickle.load(open(pca_path, "rb")) if os.path.exists(pca_path) else None

            models_data[key] = {
                "model": model,
                "scaler": scaler,
                "features": features,
                "pca": pca,
                "folder_name": folder
            }

            for f, (low, high) in feature_ranges.items():
                all_feature_ranges[f].append((low, high))

        except Exception as e:
            st.warning(f"Could not load model {folder}: {e}")

    global_ranges = {
        f: (min(r[0] for r in ranges), max(r[1] for r in ranges))
        for f, ranges in all_feature_ranges.items()
    }

    return models_data, global_ranges


models_data, global_ranges = load_all_models()

# =====================================================
# CLASSIFY FEATURES
# =====================================================
feature_counts = defaultdict(int)
models_for_classification = {k: v for k, v in models_data.items() if k != "category_scale"}

for data in models_for_classification.values():
    for f in data["features"]:
        feature_counts[f] += 1

common_features = sorted([f for f, c in feature_counts.items() if c > 1])
unique_features_map = {
    k: [f for f in v["features"] if feature_counts[f] == 1]
    for k, v in models_for_classification.items()
}

# =====================================================
# USER-ADJUSTABLE PARAMETER RANGES (HIDDEN EXPANDER)
# =====================================================
user_ranges = {}

with st.expander("⚙️ Click to adjust parameter ranges (Optional)"):
    st.markdown("You can change min/max range for sliders for experimentation.")

    # --- Common features ---
    st.markdown("**Common Features**")
    for f in common_features:
        low, high = global_ranges.get(f, (0.0, 100.0))
        col1, col2 = st.columns(2)
        with col1:
            min_val = st.number_input(f"Min for {f}", value=float(low), key=f"{f}_min")
        with col2:
            max_val = st.number_input(f"Max for {f}", value=float(high), key=f"{f}_max")
        if min_val >= max_val:
            max_val = min_val + 1
        user_ranges[f] = (min_val, max_val)

    # --- Unique features for each model ---
    for model_key in sorted(models_for_classification.keys()):
        u_features = unique_features_map.get(model_key, [])
        if not u_features:
            continue
        st.markdown(f"**Unique Features for {EMOJI_MAP.get(model_key,'')} {model_key.replace('_',' ').title()}**")
        for f in u_features:
            low, high = global_ranges.get(f, (0.0, 100.0))
            col1, col2 = st.columns(2)
            with col1:
                min_val = st.number_input(f"Min for {f}", value=float(low), key=f"{model_key}_{f}_min")
            with col2:
                max_val = st.number_input(f"Max for {f}", value=float(high), key=f"{model_key}_{f}_max")
            if min_val >= max_val:
                max_val = min_val + 1
            user_ranges[f] = (min_val, max_val)

st.divider()

# =====================================================
# COMMON PARAMETERS (SLIDERS)
# =====================================================
inputs = {}
st.subheader("🎛️ Process Parameters")
st.markdown("### Common Parameters")

cols = st.columns(2)
for i, f in enumerate(common_features):
    low, high = user_ranges.get(f, global_ranges.get(f, (0.0, 100.0)))
    if low == high:
        high = low + 1
    with cols[i % 2]:
        inputs[f] = st.slider(f, float(low), float(high), float((low + high)/2))

st.divider()

# =====================================================
# UNIQUE PARAMETERS + INLINE PREDICTIONS
# =====================================================
for model_key in sorted(models_for_classification.keys()):

    emoji = EMOJI_MAP.get(model_key, "🔹")
    name = models_data[model_key]["folder_name"].replace("_", " ").title()
    stats = MODEL_STATS.get(model_key, {})
    threshold = stats.get("threshold", 0.5)

    left_col, right_col = st.columns([0.7, 0.3])

    # ---------- LEFT ----------
    with left_col:
        st.markdown(f"### {emoji} {name} — Unique")
        ucols = st.columns(2)
        for i, f in enumerate(unique_features_map.get(model_key, [])):
            low, high = user_ranges.get(f, global_ranges.get(f, (0.0, 100.0)))
            if low == high:
                high = low + 1
            with ucols[i % 2]:
                inputs[f] = st.slider(
                    f, float(low), float(high),
                    float((low + high)/2),
                    key=f"{model_key}_{f}"
                )

    # ---------- RIGHT ----------
    with right_col:
        data = models_data[model_key]

        X = pd.DataFrame([[inputs[f] for f in data["features"]]],
                         columns=data["features"])
        Xs = data["scaler"].transform(X)
        Xf = data["pca"].transform(Xs) if data["pca"] else Xs

        score = data["model"].decision_function(Xf)[0]
        prob = 1 / (1 + np.exp(-score))
        present = prob >= threshold

        st.markdown("### 📊 Prediction")
        if present:
            st.success("Present")
        else:
            st.error("Absent")

        st.markdown(f"**Threshold:** {threshold}")

        c1, c2 = st.columns(2)
        c1.metric("Probability Score", f"{prob:.2f}")
        c2.metric("Decision Score", f"{score:.2f}")

        c3, c4 = st.columns(2)
        c3.metric("Train Accuracy", stats.get("train"))
        c4.metric("Test Accuracy", stats.get("test"))

    st.divider()

# =====================================================
# CATEGORY SCALE (FULL WIDTH)
# =====================================================
if "category_scale" in models_data:

    st.markdown("## ⚖️ Category Scale Prediction")

    data = models_data["category_scale"]
    stats = MODEL_STATS["category_scale"]
    threshold = stats["threshold"]

    X = pd.DataFrame([[inputs.get(f, 0) for f in data["features"]]],
                     columns=data["features"])
    Xs = data["scaler"].transform(X)
    Xf = data["pca"].transform(Xs) if data["pca"] else Xs

    score = data["model"].decision_function(Xf)[0]
    prob = 1 / (1 + np.exp(-score))
    quality = "GOOD" if prob >= threshold else "BAD"

    # Row 1
    r1, r2, r3 = st.columns(3)
    r1.metric("Predicted Quality", quality)
    r2.metric("Probability Score", f"{prob:.2f}")
    r3.metric("Decision Score", f"{score:.2f}")

    # Row 2
    r4, r5, r6 = st.columns(3)
    r4.metric("Threshold", threshold)
    r5.metric("Train Accuracy", stats["train"])
    r6.metric("Test Accuracy", stats["test"])

    st.divider()

    st.markdown(
        f"**The model is {prob * 100:.1f}% confident towards "
        f"{quality} quality whisky.**"
    )

    st.markdown(""" 
**Model Used:** Linear SVC  
**Decision Threshold:** 0.76  

**Advantage of Linear SVC:**  
Performs well with high-dimensional feature spaces, is robust to multicollinearity,  
and provides clear decision boundaries for binary classification tasks.
""")
