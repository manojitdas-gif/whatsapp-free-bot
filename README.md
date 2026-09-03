# 24×7 WhatsApp Customer Requirement Automation System (Electrical Dealership)

Production-ready, continuously running automated WhatsApp customer enquiry collection system.
Operates 24×7 in the cloud without requiring your personal computer to stay on.

---

## 🌟 Key Architecture & Capabilities

1. **24×7 Cloud Operation:** Deploys as a Docker container or managed cloud service (Render, Railway, Fly.io, AWS, DigitalOcean). Operates independently when local PC is turned off.
2. **Deterministic Response Engine:** Exact 3 primary customer responses matching specifications:
   - **Response 1:** All required information available ➔ marks `COMPLETED`.
   - **Response 2:** Product requirements missing ➔ requests product details.
   - **Response 3:** Product requirements present, but customer/business details missing ➔ requests business details.
3. **Burst Debounce Queue:** Patiently waits for 1.5–2.0 seconds of silence when a customer types multiple messages in quick succession ("Hi" ➔ "Need 50 LED bulbs" ➔ "For my shop") and generates exactly **ONE** response.
4. **Idempotency:** Rejects duplicate WhatsApp webhook deliveries.
5. **Universal Document & OCR Extraction:**
   - Plain text WhatsApp conversations
   - Photos, screenshots, scans via OCR
   - PDFs (scanned and digital)
   - Spreadsheets (.xlsx, .csv) with intelligent product line filtering
   - Word documents (.docx)
6. **Master 9-Column Dataset:** Updates in-place by WhatsApp Number:
   - `First Contact Date (IST)`
   - `Last Contact Date (IST)`
   - `Contact Person Name`
   - `WhatsApp Number`
   - `Email ID`
   - `Company / Business Name`
   - `GST Number`
   - `Complete Address`
   - `Customer Requirements Details`
7. **Live Admin Dashboard:** Real-time metrics, search filter, conversation drawer, and 1-click Excel export.

---

## 🚀 Quick Start (Local Run)

```powershell
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run automated tests (all 12 test cases)
pytest tests/test_all_12_cases.py -v

# 3. Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

- **Admin Dashboard:** `http://localhost:8080/admin`
- **Health Check:** `http://localhost:8080/health`
- **Excel Download:** `http://localhost:8080/export/excel`

---

## 🌐 24×7 Production Cloud Deployment (PC Turned OFF)

### Option A: 1-Click Deploy on Render (Recommended Free/Low Cost)
1. Push code to your GitHub repository: `https://github.com/manojitdas-gif/whatsapp-free-bot`
2. Go to [https://dashboard.render.com](https://dashboard.render.com)
3. Click **New +** ➔ **Blueprint** ➔ Select your repository.
4. Render will read `render.yaml` and provision:
   - A continuously running Python Web Service (FastAPI)
   - A managed PostgreSQL database
5. Copy your Render service URL (e.g. `https://whatsapp-bot.onrender.com`).

### Option B: Docker Compose on VPS (DigitalOcean / Hetzner / AWS)
```bash
git clone https://github.com/manojitdas-gif/whatsapp-free-bot.git
cd whatsapp-free-bot
docker-compose -f docker/docker-compose.yml up -d
```

---

## 📱 Meta WhatsApp Cloud API Setup (100% Official & Free Tier)

Meta provides **1,000 free service conversations every month**:

1. Go to [Meta for Developers](https://developers.facebook.com/) and create a Business App.
2. Under **WhatsApp** ➔ **Configuration**:
   - **Callback URL:** `https://your-domain.com/webhook`
   - **Verify Token:** `whatsapp_verify_token_2026` (or set in `.env`)
   - Subscribe to the **`messages`** webhook field.
3. Under **API Setup**:
   - Copy **Phone Number ID** ➔ paste into `WHATSAPP_PHONE_NUMBER_ID`
   - Generate Permanent System User Access Token ➔ paste into `WHATSAPP_ACCESS_TOKEN`
4. Deploy with `WHATSAPP_PROVIDER=meta_cloud` in your environment.

---

## 🧪 Verification & Automated Tests

All 12 business and technical test cases pass cleanly:
```
tests/test_all_12_cases.py::test_1_customer_provides_everything_in_first_message PASSED
tests/test_all_12_cases.py::test_2_customer_only_says_hi PASSED
tests/test_all_12_cases.py::test_3_customer_sends_product_photo_only PASSED
tests/test_all_12_cases.py::test_4_customer_sends_pdf_with_requirements_and_company PASSED
tests/test_all_12_cases.py::test_5_customer_sends_burst_messages PASSED
tests/test_all_12_cases.py::test_6_customer_sends_no_further_reply PASSED
tests/test_all_12_cases.py::test_7_duplicate_webhook_idempotency PASSED
tests/test_all_12_cases.py::test_8_company_details_first_product_later PASSED
tests/test_all_12_cases.py::test_9_customer_corrects_gst_number PASSED
tests/test_all_12_cases.py::test_10_image_containing_gst_address_product PASSED
tests/test_all_12_cases.py::test_11_excel_product_list_extraction PASSED
tests/test_all_12_cases.py::test_12_server_restart_preserves_state PASSED

======================= 12 passed in 49.62s =======================
```
