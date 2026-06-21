import streamlit as st
import requests
import time

# Configure the web page layout
st.set_page_config(page_title="AI Document Agent Dashboard", layout="wide")

FASTAPI_URL = "http://127.0.0.1:8000"

st.title("📄 Intelligent Document Agent Dashboard")
st.markdown("Upload a medical bill or EOB PDF to process it using local AI agents and verify billing data accuracy.")

st.markdown("---")

# Create two visual columns on the screen (Left for Upload, Right for Results)
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("1. Upload Ingestion Channel")
    uploaded_file = st.file_uploader("Drag and drop your medical statement PDF here", type=["pdf"])
    
    if uploaded_file is not None:
        if st.button("🚀 Fire Agent Pipeline", use_container_width=True):
            with st.spinner("Uploading file to ingestion queue..."):
                # Prepare the multipart file payload to hit FastAPI
                files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")}
                
                try:
                    # Hit our async FastAPI ingestion endpoint
                    response = requests.post(f"{FASTAPI_URL}/process-bill/", files=files)
                    
                    if response.status_code == 202:
                        res_data = response.json()
                        task_id = res_data["task_id"]
                        st.success(f"File accepted! Task ID: {task_id[:8]}...")
                        
                        # Store the task ID in session state so the screen remembers it during refresh loops
                        st.session_state["active_task_id"] = task_id
                    else:
                        st.error(f"Ingestion failed with status: {response.status_code}")
                except Exception as e:
                    st.error(f"Could not connect to FastAPI backend: {e}")

with col2:
    st.subheader("2. Real-Time Agent Execution & Results")
    
    # Check if we have an active task running in the background
    if "active_task_id" in st.session_state:
        task_id = st.session_state["active_task_id"]
        
        # Create a placeholder container on the screen we can dynamically rewrite
        status_container = st.empty()
        
        # Polling loop: Hit the GET endpoint every 2 seconds until it finishes processing
        with st.spinner("Agent is actively analyzing document pages..."):
            while True:
                try:
                    status_res = requests.get(f"{FASTAPI_URL}/tasks/{task_id}")
                    job_data = status_res.json()
                    status = job_data["status"]
                    
                    if status in ["QUEUED", "PROCESSING"]:
                        status_container.info(f"⏳ Current Agent State: **{status}**")
                        time.sleep(2)  # Wait 2 seconds before checking again
                    else:
                        # The background job finished! Break out of the loop
                        status_container.empty()
                        break
                except Exception as e:
                    st.error(f"Error checking task status: {e}")
                    break
        
        # --- Render the final output beautifully on the screen ---
        if job_data["status"] == "COMPLETED":
            st.balloons() # Quick celebratory UI animation!
            st.success("✅ Extraction Completed & Math Audited Successfully!")
        elif job_data["status"] == "WARNING":
            st.warning("⚠️ Saved with Warnings: The line item totals do not match the summary amount due.")
        elif job_data["status"] == "FAILED":
            st.error(f"❌ Background worker failed: {job_data.get('error_log')}")
            
        # Display the extracted structures if they exist
        if job_data.get("extracted_data"):
            ext = job_data["extracted_data"]
            
            # Show summary metrics
            m_col1, m_col2 = st.columns(2)
            m_col1.metric("Extracted Provider", ext.get("provider_name", "Unknown"))
            m_col2.metric("Total Amount Due", f"${ext.get('total_amount_due', 0.0):,.2f}")
            
            # Display itemized breakdown inside a clean data table
            st.markdown("### Itemized Service Breakdown")
            line_items = ext.get("line_items", [])
            if line_items:
                st.table(line_items)
            else:
                st.info("No explicit line items extracted.")
                
            # Show any validation warnings explicitly
            audit = ext.get("audit_metadata", {})
            if audit.get("validation_errors"):
                with st.expander("View Audit Mismatch Details"):
                    for err in audit["validation_errors"]:
                        st.write(f"🔴 {err}")
    else:
        st.info("Waiting for a document to be uploaded on the left channel...")