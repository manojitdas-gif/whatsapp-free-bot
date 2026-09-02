"""
cloud_sync.py — 24/7 Cloud Lead Synchronization & Local Desktop Downloader.

Provides two-way synchronization:
1. Cloud Engine -> Google Sheets (Logs leads in real time 24/7 via free webhook)
2. PC Startup -> Syncs Google Sheets back into Desktop Excel files:
   - WhatsApp_Conversations.xlsx
   - WhatsApp_Leads_SHARED.xlsx
   - WhatsApp_Leads_Live.csv
"""

import os
import sys
import json
import csv
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from excel_logger import log_customer_lead, MASTER_EXCEL, SHARED_EXCEL, LIVE_CSV

IST = timezone(timedelta(hours=5, minutes=30))

# Default Google Apps Script Webhook URL (Configurable via environment or local config)
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cloud_config.json")


def get_cloud_webhook_url() -> str:
    """Reads configured webhook URL or returns empty string."""
    if os.environ.get("GOOGLE_SHEETS_WEBHOOK"):
        return os.environ["GOOGLE_SHEETS_WEBHOOK"].strip()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("webhook_url", "").strip()
        except Exception:
            pass
    return ""


def set_cloud_webhook_url(url: str) -> None:
    """Saves webhook URL to config file."""
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"webhook_url": url}, f, indent=2)
    print(f"[CLOUD SYNC] Saved Google Sheets Webhook URL: {url}", flush=True)


def push_lead_to_cloud(lead_dict: dict) -> bool:
    """Sends a lead payload to the Google Sheets cloud webhook."""
    webhook_url = get_cloud_webhook_url()
    if not webhook_url:
        return False

    try:
        data = json.dumps(lead_dict).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            if status in (200, 302):
                print(f"[CLOUD SYNC] Lead synced to Google Sheets for {lead_dict.get('phone')}", flush=True)
                return True
    except Exception as e:
        print(f"[CLOUD SYNC ERROR] Failed to push to Google Sheets: {e}", flush=True)
    return False


def pull_cloud_leads_to_desktop() -> int:
    """
    Downloads all leads from the cloud Google Sheet and updates
    the Desktop Excel files when the user powers on their PC.
    """
    webhook_url = get_cloud_webhook_url()
    if not webhook_url:
        return 0

    try:
        # Request CSV / JSON export from webhook
        req = urllib.request.Request(f"{webhook_url}?action=export", method="GET")
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                raw_json = resp.read().decode("utf-8")
                records = json.loads(raw_json)
                if isinstance(records, list) and records:
                    synced_count = 0
                    for row in records:
                        phone = row.get("phone", "")
                        name = row.get("name", "Customer")
                        reqs = row.get("requirements", "")
                        if phone:
                            log_customer_lead(
                                sender_phone=phone,
                                sender_name=name,
                                message_text=reqs,
                                analyzed_products=reqs,
                            )
                            synced_count += 1
                    print(f"[CLOUD SYNC] Successfully synced {synced_count} leads to Desktop Excel!", flush=True)
                    return synced_count
    except Exception as e:
        print(f"[CLOUD SYNC ERROR] Pull failed: {e}", flush=True)
    return 0


# Template for Google Apps Script to paste into Google Sheets
GOOGLE_APPS_SCRIPT_CODE = """
function doPost(e) {
  try {
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
    if (sheet.getLastRow() === 0) {
      sheet.appendRow([
        "S.No.", "First Contact Date (IST)", "Last Contact Date (IST)", 
        "Contact Person Name", "WhatsApp Number", "Email ID", 
        "Company / Business Name", "GST Number", "Complete Address", 
        "Customer Requirements Details"
      ]);
      sheet.getRange(1, 1, 1, 10).setFontWeight("bold").setBackground("#2E7D32").setFontColor("#FFFFFF");
    }
    
    var data = JSON.parse(e.postData.contents);
    var phone = String(data.phone || "").trim();
    var values = sheet.getDataRange().getValues();
    var rowIndex = -1;
    
    for (var i = 1; i < values.length; i++) {
      if (String(values[i][4]).trim() === phone) {
        rowIndex = i + 1;
        break;
      }
    }
    
    if (rowIndex > 0) {
      // Update existing customer
      if (data.last_contact) sheet.getRange(rowIndex, 3).setValue(data.last_contact);
      if (data.email) sheet.getRange(rowIndex, 6).setValue(data.email);
      if (data.company) sheet.getRange(rowIndex, 7).setValue(data.company);
      if (data.gst) sheet.getRange(rowIndex, 8).setValue(data.gst);
      if (data.address) sheet.getRange(rowIndex, 9).setValue(data.address);
      if (data.requirements) {
        var existing = String(sheet.getRange(rowIndex, 10).getValue() || "");
        if (existing.indexOf(data.requirements) === -1) {
          sheet.getRange(rowIndex, 10).setValue(existing ? existing + " | " + data.requirements : data.requirements);
        }
      }
    } else {
      // New customer row
      var sNo = sheet.getLastRow();
      sheet.appendRow([
        sNo, data.first_contact || "", data.last_contact || "",
        data.name || "Customer", phone, data.email || "",
        data.company || "", data.gst || "", data.address || "",
        data.requirements || ""
      ]);
    }
    
    return ContentService.createTextOutput(JSON.stringify({status: "ok"})).setMimeType(ContentService.MimeType.JSON);
  } catch(err) {
    return ContentService.createTextOutput(JSON.stringify({status: "error", message: err.toString()})).setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var values = sheet.getDataRange().getValues();
  var result = [];
  for (var i = 1; i < values.length; i++) {
    result.push({
      s_no: values[i][0],
      first_contact: values[i][1],
      last_contact: values[i][2],
      name: values[i][3],
      phone: values[i][4],
      email: values[i][5],
      company: values[i][6],
      gst: values[i][7],
      address: values[i][8],
      requirements: values[i][9]
    });
  }
  return ContentService.createTextOutput(JSON.stringify(result)).setMimeType(ContentService.MimeType.JSON);
}
"""


if __name__ == "__main__":
    print("Testing cloud_sync module...")
    url = get_cloud_webhook_url()
    if url:
        print(f"Configured Webhook: {url}")
        pull_cloud_leads_to_desktop()
    else:
        print("No Webhook configured yet. Save Google Apps Script code to create free cloud sync.")
