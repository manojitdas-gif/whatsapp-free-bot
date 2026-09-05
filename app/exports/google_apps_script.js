/**
 * WhatsApp Lead Automation — Google Sheets Real-Time Sync Script
 * 
 * SETUP INSTRUCTIONS:
 * 1. Open your Google Sheet.
 * 2. Set the 9 headers in Row 1 (Col A to I):
 *    A: First Contact Date
 *    B: Last Contact Date
 *    C: Contact Person Name
 *    D: WhatsApp Number
 *    E: Email ID
 *    F: Company / Business Name
 *    G: GST Number
 *    H: Complete Address
 *    I: Customer Requirements Details
 * 3. In Google Sheets, click: Extensions -> Apps Script
 * 4. Paste this entire script into Code.gs (replace any existing code).
 * 5. Click "Deploy" -> "New deployment".
 * 6. Under "Select type", select "Web app".
 * 7. Set:
 *    - Description: WhatsApp Sync
 *    - Execute as: Me
 *    - Who has access: Anyone
 * 8. Click "Deploy", copy the Web App URL (starts with https://script.google.com/macros/s/...)
 * 9. Set this URL as GOOGLE_SHEET_WEBHOOK_URL in your cloud bot environment!
 */

function doPost(e) {
  try {
    var data = JSON.parse(e.postData.contents);
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
    
    // Normalize phone number to match unique rows
    var phone = String(data.whatsapp_number || "").replace(/[^0-9]/g, "");
    var last10 = phone.slice(-10);
    
    var lastRow = sheet.getLastRow();
    var rowIndex = -1;
    
    // Find if phone already exists in Column D (Column 4)
    if (lastRow > 1) {
      var phoneValues = sheet.getRange(2, 4, lastRow - 1, 1).getValues();
      for (var i = 0; i < phoneValues.length; i++) {
        var existingPhone = String(phoneValues[i][0] || "").replace(/[^0-9]/g, "");
        if (existingPhone && (existingPhone.slice(-10) === last10)) {
          rowIndex = i + 2; // 1-indexed, starting from row 2
          break;
        }
      }
    }
    
    // Safe phone string formatted with single-quote prefix so Google Sheets never evaluates it as a formula error
    var rawPhone = String(data.whatsapp_number || "").trim();
    var phoneText = rawPhone;
    if (phoneText && !phoneText.startsWith("'")) {
      phoneText = "'" + phoneText;
    }

    // Row data to set (9 columns)
    var rowData = [
      data.first_contact_date || Utilities.formatDate(new Date(), "Asia/Kolkata", "yyyy-MM-dd"),
      data.last_contact_date || Utilities.formatDate(new Date(), "Asia/Kolkata", "yyyy-MM-dd"),
      data.contact_person_name || data.company_name || "",
      phoneText,
      data.email_id || "",
      data.company_name || "",
      data.gst_number || "",
      data.complete_address || "",
      data.requirements_summary || ""
    ];
    
    if (rowIndex > 0) {
      // In-place row update (does not duplicate rows)
      sheet.getRange(rowIndex, 1, 1, 9).setValues([rowData]);
    } else {
      // Insert new row
      sheet.appendRow(rowData);
      rowIndex = sheet.getLastRow();
    }
    
    return ContentService.createTextOutput(JSON.stringify({
      status: "success",
      row: rowIndex,
      phone: data.whatsapp_number
    })).setMimeType(ContentService.MimeType.JSON);
    
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      message: err.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

function doGet(e) {
  return ContentService.createTextOutput(JSON.stringify({
    status: "online",
    service: "WhatsApp Google Sheets Live Sync"
  })).setMimeType(ContentService.MimeType.JSON);
}
