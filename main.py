import io
import os
import uuid
import shutil
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import List
from pypdf import PdfReader
from motor.motor_asyncio import AsyncIOMotorClient
from langchain_ollama import ChatOllama

app = FastAPI(title="Asynchronous Document Processing Agent")

# ---- Infrastructure Setup ----
MONGO_DETAILS = "mongodb://localhost:27017"
client = AsyncIOMotorClient(MONGO_DETAILS)
db = client["document_agent_db"]
collection = db["async_extracted_bills"]

UPLOAD_DIR = "uploaded_files"
os.makedirs(UPLOAD_DIR, exist_ok=True)

class BillItem(BaseModel):
    service_description: str = Field(description="Type of service or procedure, e.g., 'Office Visits' or 'Laboratory'")
    amount_billed: float = Field(description="The full raw amount charged by the provider before discounts")

class PageLineItems(BaseModel):
    line_items: List[BillItem] = Field(description="List of individual service line items found on this page. Return empty list if none found.")

# For processing the summary block pages
class BillSummary(BaseModel):
    provider_name: str = Field(description="The insurance provider or hospital name, e.g., 'United Healthcare Global'")
    total_amount_due: float = Field(description="The final total amount the patient owes the provider (Total Amount You Owe)")


llm = ChatOllama(model="llama3", temperature=0)
 # Initialize two separate structured LLM workers
summary_worker = llm.with_structured_output(BillSummary)
items_worker = llm.with_structured_output(PageLineItems)


async def background_pdf_processor(task_id: str, file_path: str, orginal_filename: str):
   

    try:
        await collection.update_one({"task_id": task_id}, {"$set": {"status": "PROCESSING"}})
        
        pdf_reader = PdfReader(file_path)
        
        # Initialize our aggregators
        final_provider_name = "Unknown Provider"
        final_total_amount_due = 0.0
        all_line_items = []
        
       

        # Loop through pages individually
        for page_num, page in enumerate(pdf_reader.pages, start=1):
            page_text = page.extract_text()
            if not page_text or not page_text.strip():
                continue
                
            print(f"📄 Scanning Page {page_num} of {len(pdf_reader.pages)}...")

            # --- Rule A: Look for Summary Data on Page 1 ---
            if page_num == 1:
                print(f"🔍 [Page {page_num}] Extracting overall billing summary...")
                summary_prompt = f"Extract the provider name and the final total amount the patient owes from this summary text:\n\n{page_text}"
                try:
                    summary_res: BillSummary = summary_worker.invoke(summary_prompt)
                    final_provider_name = summary_res.provider_name
                    final_total_amount_due = summary_res.total_amount_due
                    print(f"   Collected Summary -> Provider: {final_provider_name}, Total Owed: {final_total_amount_due}")
                except Exception as e:
                    print(f"   ⚠️ Failed to extract summary on page {page_num}: {e}")

            # --- Rule B: Look for Line Items on Breakdown Pages (e.g., Page 2) ---
            if "Billed" in page_text or "Service" in page_text or "Total" in page_text:
                print(f"📊 [Page {page_num}] Table indicators found. Extracting itemized line items...")
                items_prompt = (
                    f"Look at the itemized table on this page. Extract each service description and its corresponding 'Amount Billed'.\n"
                    f"Ignore totals or calculated summaries at the bottom of the table.\n\n"
                    f"Page Text:\n{page_text}"
                )
                try:
                    items_res: PageLineItems = items_worker.invoke(items_prompt)
                    if items_res.line_items:
                        print(f"   Collected {len(items_res.line_items)} line items from page {page_num}.")
                        all_line_items.extend(items_res.line_items)
                except Exception as e:
                    print(f"   ⚠️ Failed to extract line items on page {page_num}: {e}")

        # --- Python Post-Processing & Validation ---
        calculated_total = sum(item.amount_billed for item in all_line_items)
        math_validated = round(calculated_total, 2) == round(final_total_amount_due, 2)
        
        validation_errors = []
        if not math_validated:
            validation_errors.append(
                f"Math Mismatch: Summary total is {final_total_amount_due}, but combined line items sum to {calculated_total}."
            )
            print(f"⚠️ {validation_errors[0]}")
        else:
            print("✅ Perfect math match across pages!")

        # Build final database payload
        extracted_payload = {
            "provider_name": final_provider_name,
            "total_amount_due": final_total_amount_due,
            "line_items": [item.model_dump() for item in all_line_items],
            "audit_metadata": {
                "math_validated_successfully": math_validated,
                "validation_errors": validation_errors,
                "pages_processed": len(pdf_reader.pages)
            }
        }

        final_status = "COMPLETED" if math_validated else "WARNING"
        await collection.update_one(
            {"task_id": task_id},
            {"$set": {
                "status": final_status,
                "extracted_data": extracted_payload 
            }}
            
        )
    except Exception as exc:
        print(f"CRITICAL failure inside background worker for task {task_id}: {exc}")
        # Secure the fallback: ensure the document status tracks the failure
        await collection.update_one(
            {"task_id": task_id},
            {"$set": {
                "status": "FAILED",
                "error_log": str(exc)
            }}
        )
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

@app.post("/process-bill/", status_code=202)
async def process_medical_bill_async(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
     if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
     
     task_id = str(uuid.uuid4())

     saved_file_path = os.path.join(UPLOAD_DIR, f"{task_id}.pdf")
     with open(saved_file_path, "wb") as buffer:
         shutil.copyfileobj(file.file, buffer)

     initial_job_record = {
         "task_id": task_id,
         "file_name": file.filename,
         "status": "QUEUED",
         "extracted_data": None

     }    

     await collection.insert_one(initial_job_record)

     background_tasks.add_task(background_pdf_processor,task_id,saved_file_path,file.filename)

     return{
         "status": "accepted",
         "task_id": task_id,
         "check_status_url": f"/tasks/{task_id}"
     }

@app.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    job = await collection.find_one({"task_id": task_id})
    if not job:
        raise HTTPException(status_code=404, detail="Task Identifier not found")
    
    return {
        "task_id": job["task_id"],
        "file_name": job["file_name"],
        "status": job["status"],
        "extracted_data": job.get("extracted_data"),
        "error_log": job.get("error_log")
    }

    
    