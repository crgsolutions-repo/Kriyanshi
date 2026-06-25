import streamlit as st
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LinearRegression

# Load the dataset
df = pd.read_csv(r"D:\CRG\Diageo\final.csv")

# Streamlit app title
st.title("Dynamic Regression Model Interface")

# Allow user to select the target and independent variables
st.sidebar.header("Model Configuration")
target = st.sidebar.selectbox("Select Target Variable", df.columns, index=list(df.columns).index('Rating'))
features = st.sidebar.multiselect("Select Independent Variables", df.columns, default=[
    'UT_Fruit-No_rating', 'Esters-No_rating', '_Dried_Fruit-No_rating', 'Brown spices No_rating', 
    'UT_Vanilla-No_rating', 'UT_Wood-No_rating', 'New_Wood-No_rating', 'Aged_Wood-No_rating', 
    'UT_Smoky-No_rating', 'UT_Rubber-No_rating', 'UT_Sugars-_No_rating', 'Caramel_rating', 
    'Brown_Sugar-No_rating', 'UT Floral No_rating', 'UT__Green_rating', 'Hay/Tea-No_rating', 
    'UT_Dry_Fragant-_Pa_rating', 'Sweet_rating', 'Bitter_rating', 'Sour_rating', 
    'Alcoholic_strength_rating', 'Viscous_rating'
])

# If the user hasn't selected any features, show a warning
if not features:
    st.warning("Please select at least one independent variable.")
else:
    # Split the data
    X = df[features]
    y = df[target]

    # Split the data into training and testing sets
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Normalize the feature values
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    # Initialize and train the linear regression model
    model = LinearRegression()
    model.fit(X_train_scaled, y_train)

    # Display feature weights
    st.sidebar.subheader("Feature Weights")
    feature_weights = dict(zip(features, model.coef_))
    for feature, weight in feature_weights.items():
        st.sidebar.write(f"{feature}: {weight:.4f}")

    # Sliders for adjusting feature values
    st.subheader("Adjust Feature Values")
    feature_values = {}
    for feature in features:
        min_val, max_val = float(df[feature].min()), float(df[feature].max())
        mean_val = float(df[feature].mean())
        feature_values[feature] = st.slider(feature, min_val, max_val, mean_val)

    # Predict the final rating
    def calculate_final_rating(feature_values):
        # Convert the feature values to a list
        feature_list = [feature_values[feature] for feature in features]
        
        # Rescale the feature values
        scaled_features = scaler.transform([feature_list])[0]
        
        # Predict the final rating
        final_rating = model.predict([scaled_features])[0]
        return final_rating

    # Display the predicted rating
    final_rating = calculate_final_rating(feature_values)
    st.subheader(f"Predicted {target}: {final_rating:.2f}")

    # Plot feature impacts
    st.subheader("Feature Impact (Weights)")
    st.bar_chart(pd.DataFrame({"Feature": list(feature_weights.keys()), 
                               "Weight": list(feature_weights.values())}).set_index("Feature"))
