import streamlit as st
import time
import geocoder
from keras.preprocessing import image
from PrecisionFarming import PrecisionFarming

def update_city(lat, long):
    """Update the city and state based on latitude and longitude."""
    arc = geocoder.arcgis([lat, long], method="reverse")
    st.session_state.loc = f"{arc.city}, {arc.state}"

def update_lat_long(location):
    """Update the latitude and longitude based on the location."""
    st.session_state.lat, st.session_state.long = geocoder.arcgis(
        location).latlng

def show_completion_animation():
    """Show an animated completion indicator"""
    with st.spinner('🎯 Analysis Complete! Preparing results...'):
        time.sleep(2)  # Give a moment to see the animation
    st.balloons()  # Add some celebration effects

def create_streamlit_app():
    st.set_page_config(page_title="Precision Farming Assistant",
                       page_icon="🌾",
                       layout="wide")

    st.title("🌾 Precision Farming Assistant")

    if "pf" not in st.session_state:
        st.session_state.pf = PrecisionFarming()
    if "loc" not in st.session_state:
        st.session_state.loc = "Concord, NC"
        st.session_state.lat, st.session_state.long = geocoder.arcgis(
            st.session_state.loc).latlng

    # Create two main columns
    input_col, status_col = st.columns([1, 2])

    # Left column for inputs
    with input_col:
        st.header("Input Parameters")
        loc = st.text_input(
            "Location",
            key="loc",
            on_change=lambda: update_lat_long(st.session_state.loc))

        latitude = st.number_input(
            "Latitude",
            value=st.session_state.lat,
            on_change=lambda: update_city(st.session_state.lat, st.session_state.long))
        longitude = st.number_input(
            "Longitude",
            value=st.session_state.long,
            on_change=lambda: update_city(st.session_state.lat, st.session_state.long))
        soil_ph = st.number_input("Soil pH", value=6.5, step=0.1)
        soil_moisture = st.number_input("Soil Moisture", value=30)
        area = st.number_input("Area (acres)", value=10, step=1)
        crop = st.selectbox("Select Crop", ["Corn", "Soybean", "Cotton"])
        insect = st.file_uploader("Upload Insect Image", type=["jpg", "png"])
        leaf = st.file_uploader("Upload Leaf Disease Image", type=["jpg", "png"])

        analyze_button = st.button("Analyze Farm Conditions")

    # Right column for status and results
    with status_col:
        st.header("Analysis Status & Results")
        
        # Create placeholder for dynamic content
        display_area = st.empty()
        
        if analyze_button:
            # Create a container within the placeholder for progress
            with display_area.container():
                status_area = st.container()
                progress_area = st.container()
                tool_progress = {}

                def update_status(message, progress, tool_name):
                    with status_area:
                        if progress == -1:
                            st.error(message)
                            return

                        if tool_name not in tool_progress:
                            with progress_area:
                                tool_progress[tool_name] = {
                                    'status': st.empty(),
                                    'bar': st.progress(0)
                                }

                        prog = tool_progress[tool_name]
                        prog['status'].info(f"{tool_name}: {message}")
                        prog['bar'].progress(int(progress))

                try:
                    # Process images if provided
                    insect_img = None
                    leaf_img = None

                    if insect:
                        insect_img = image.load_img(insect, target_size=(224, 224))
                    if leaf:
                        leaf_img = image.load_img(leaf, target_size=(224, 224))

                    # Get insights with progress tracking
                    insights = st.session_state.pf.get_insights(
                        soil_ph=soil_ph,
                        soil_moisture=soil_moisture,
                        latitude=latitude,
                        longitude=longitude,
                        area_acres=area,
                        crop=crop,
                        insect=insect_img,
                        leaf=leaf_img,
                        status_callback=update_status)

                    # Show completion animation
                    show_completion_animation()

                    # Clear the progress display and show results
                    display_area.empty()
                    with display_area.container():
                        st.success("✨ Analysis Complete!")
                        st.markdown("### Farm Analysis Results")
                        # Add a visual separator
                        st.markdown("---")
                        # Display the results in a clean format
                        st.markdown(insights)

                except Exception as e:
                    st.error(f"An error occurred: {str(e)}")

if __name__ == "__main__":
    create_streamlit_app()