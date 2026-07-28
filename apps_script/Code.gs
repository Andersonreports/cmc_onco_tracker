
var DRIVE_FOLDER_ID = '1nWYIKZKppCHEhuc9WSG5mwLnHGqLeYjq';
var META_SHEET_NAME = '_meta';
var DATA_SHEET_NAME = 'Sheet1';

function getDataSheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(DATA_SHEET_NAME);
  if (!sheet) {
    throw new Error('Data sheet "' + DATA_SHEET_NAME + '" not found. Rename the main tracker tab to "' + DATA_SHEET_NAME + '".');
  }
  return sheet;
}

var MAIL_TO = 'drsriharikrishnaa@andersondiagnostics.in';


function doGet(e) {
  if (e && e.parameter && e.parameter.action) {
    var action = e.parameter.action;
    if (action === 'getAll')       return getAllAction(e.parameter.includeFiles !== '0');
    if (action === 'listFiles')    return listFilesAction(e.parameter.batch);
    if (action === 'listAllFiles') return listAllFilesAction();
    if (action === 'getFile')      return getFileAction(e.parameter.fileId);
    if (action === 'getMeta')      return getMetaAction(e.parameter.key);
    return handleAction(e.parameter);
  }
  try {
    var sheet = getDataSheet();
    var data  = sheet.getDataRange().getDisplayValues();
    var headers = data[0];
    var rows = data.slice(1).filter(function(r){return r.some(function(c){return c !== '';})}).map(function(r){
      var obj = {}; headers.forEach(function(h, i){ obj[h] = r[i]; }); return obj;
    });
    return jsonOut(rows);
  } catch(err) {
    return jsonOut({ error: err.message });
  }
}

function doPost(e) {
  try {
    var p = JSON.parse(e.postData.contents);
    if (p.action === 'sendDNARNAEmail')       return sendDNARNAEmail(p.batch, p.pptBase64||null, p.pptName||null, p.customSubject||null, p.customBody||null, p.to||null, p.cc||null);
    if (p.action === 'sendLibraryPrepEmail')  return sendLibraryPrepEmail(p.batch, p.pptBase64||null, p.pptName||null, p.customSubject||null, p.customBody||null, p.to||null, p.cc||null);
    if (p.action === 'sendDataTransferEmail') return sendDataTransferEmail(p.batch, p.customSubject||null, p.customBody||null, p.files||null, p.fileIds||null, p.to||null, p.cc||null);
    if (p.action === 'sendDataUploadEmail')   return sendDataUploadEmail(p.batch, p.customSubject||null, p.customBody||null, p.files||null, p.fileIds||null, p.to||null, p.cc||null);
    if (p.action === 'uploadFile')            return uploadFileAction(p.batch, p.category, p.fileName, p.base64);
    if (p.action === 'deleteFile')            return deleteFileAction(p.fileId);
    if (p.action === 'setMeta')               return setMetaAction(p.key, p.value);
    if (p.action === 'setMetaBatch')          return setMetaBatchAction(p.items);
    return jsonOut({ error: 'Unknown action' });
  } catch(err) {
    return jsonOut({ error: err.message });
  }
}

function handleAction(params) {
  try {
    if (params.action === 'sendDNARNAEmail')       return sendDNARNAEmail(params.batch, null, null, null, null, params.to||null, params.cc||null);
    if (params.action === 'sendLibraryPrepEmail')  return sendLibraryPrepEmail(params.batch, null, null, null, null, params.to||null, params.cc||null);
    if (params.action === 'sendDataTransferEmail') return sendDataTransferEmail(params.batch, null, null, null, null, params.to||null, params.cc||null);
    if (params.action === 'sendDataUploadEmail')   return sendDataUploadEmail(params.batch, null, null, null, null, params.to||null, params.cc||null);
    return jsonOut({ error: 'Unknown action' });
  } catch(err) {
    return jsonOut({ error: err.message });
  }
}


var FILE_CATEGORIES = ['ppt','lib_ppt','dna','lib','dt','du'];

function uploadFileAction(batch, category, fileName, base64) {
  if (!batch || !category || !fileName || !base64) return jsonOut({ error: 'Missing required fields' });
  if (FILE_CATEGORIES.indexOf(category) === -1) return jsonOut({ error: 'Invalid category (use ' + FILE_CATEGORIES.join(', ') + ')' });

  var root        = DriveApp.getFolderById(DRIVE_FOLDER_ID);
  var batchFolder = getOrCreateFolder(root, sanitizeFolderName(batch));
  var catFolder   = getOrCreateFolder(batchFolder, category);

  var existing = catFolder.getFilesByName(fileName);
  while (existing.hasNext()) existing.next().setTrashed(true);

  var blob = Utilities.newBlob(Utilities.base64Decode(base64), guessMime(fileName), fileName);
  var file = catFolder.createFile(blob);
  return jsonOut({
    success: true,
    fileId:   file.getId(),
    fileName: file.getName(),
    mimeType: file.getMimeType(),
    size:     file.getSize(),
    url:      file.getUrl()
  });
}

function emptyFileCatMap() {
  var m = {};
  FILE_CATEGORIES.forEach(function(c) { m[c] = []; });
  return m;
}

function listFilesAction(batch) {
  if (!batch) return jsonOut({ error: 'Missing batch' });
  var result = emptyFileCatMap();
  var root = DriveApp.getFolderById(DRIVE_FOLDER_ID);
  var bIt = root.getFoldersByName(sanitizeFolderName(batch));
  if (!bIt.hasNext()) return jsonOut(result);
  var bf = bIt.next();
  FILE_CATEGORIES.forEach(function(cat) {
    var cIt = bf.getFoldersByName(cat);
    if (!cIt.hasNext()) return;
    var cf = cIt.next();
    var fIt = cf.getFiles();
    while (fIt.hasNext()) {
      var f = fIt.next();
      result[cat].push({
        fileId:   f.getId(),
        fileName: f.getName(),
        mimeType: f.getMimeType(),
        size:     f.getSize(),
        url:      f.getUrl()
      });
    }
  });
  return jsonOut(result);
}

function listAllFilesAction() {
  var out = {};
  var root = DriveApp.getFolderById(DRIVE_FOLDER_ID);
  var bIt = root.getFolders();
  while (bIt.hasNext()) {
    var bf = bIt.next();
    var perBatch = emptyFileCatMap();
    FILE_CATEGORIES.forEach(function(cat) {
      var cIt = bf.getFoldersByName(cat);
      if (!cIt.hasNext()) return;
      var cf = cIt.next();
      var fIt = cf.getFiles();
      while (fIt.hasNext()) {
        var f = fIt.next();
        if (f.isTrashed()) continue;
        perBatch[cat].push({
          fileId:   f.getId(),
          fileName: f.getName(),
          mimeType: f.getMimeType(),
          size:     f.getSize()
        });
      }
    });
    out[bf.getName()] = perBatch;
  }
  return jsonOut(out);
}

function getAllAction(includeFiles) {
  includeFiles = includeFiles !== false;
  try {
    var sheet = getDataSheet();
    var data  = sheet.getDataRange().getDisplayValues();
    var headers = data[0];

    if (findHeaderIndex(headers, 'batch') === -1) {
      throw new Error('"' + DATA_SHEET_NAME + '" does not look like the tracker data sheet (no "Batch" column found). Check that the correct sheet is named "' + DATA_SHEET_NAME + '".');
    }

    var rows = data.slice(1)
      .filter(function(r){ return r.some(function(c){ return c !== ''; }); })
      .map(function(r){
        var obj = {};
        headers.forEach(function(h, i){ obj[h] = r[i]; });
        return obj;
      });

    var metaData = getMetaSheet().getDataRange().getValues();
    var meta = {};
    for (var i = 1; i < metaData.length; i++) {
      if (metaData[i][0]) meta[String(metaData[i][0])] = String(metaData[i][1]);
    }

    var response = { rows: rows, meta: meta };
    if (includeFiles) {
      var files = {};
      var root = DriveApp.getFolderById(DRIVE_FOLDER_ID);
      var bIt = root.getFolders();
      while (bIt.hasNext()) {
        var bf = bIt.next();
        var perBatch = emptyFileCatMap();
        FILE_CATEGORIES.forEach(function(cat) {
          var cIt = bf.getFoldersByName(cat);
          if (!cIt.hasNext()) return;
          var cf = cIt.next();
          var fIt = cf.getFiles();
          while (fIt.hasNext()) {
            var f = fIt.next();
            if (f.isTrashed()) continue;
            perBatch[cat].push({ fileId: f.getId(), fileName: f.getName() });
          }
        });
        files[bf.getName()] = perBatch;
      }
      response.files = files;
    }

    return jsonOut(response);
  } catch (err) {
    return jsonOut({ error: err.message || String(err) });
  }
}

function getFileAction(fileId) {
  if (!fileId) return jsonOut({ error: 'Missing fileId' });
  var file = DriveApp.getFileById(fileId);
  return jsonOut({
    fileName: file.getName(),
    mimeType: file.getMimeType(),
    size:     file.getSize(),
    base64:   Utilities.base64Encode(file.getBlob().getBytes())
  });
}

function deleteFileAction(fileId) {
  if (!fileId) return jsonOut({ error: 'Missing fileId' });
  DriveApp.getFileById(fileId).setTrashed(true);
  return jsonOut({ success: true });
}


function getMetaSheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(META_SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(META_SHEET_NAME);
    sheet.appendRow(['key', 'value', 'updated_at']);
    sheet.hideSheet();
  }
  return sheet;
}

function getMetaAction(key) {
  var sheet = getMetaSheet();
  var data  = sheet.getDataRange().getValues();
  if (key) {
    for (var i = 1; i < data.length; i++) {
      if (data[i][0] === key) return jsonOut({ value: String(data[i][1]) });
    }
    return jsonOut({ value: null });
  }
  var all = {};
  for (var i = 1; i < data.length; i++) {
    if (data[i][0]) all[data[i][0]] = String(data[i][1]);
  }
  return jsonOut(all);
}

function setMetaAction(key, value) {
  if (!key) return jsonOut({ error: 'Missing key' });
  var sheet = getMetaSheet();
  var data  = sheet.getDataRange().getValues();
  var ts    = new Date();
  for (var i = 1; i < data.length; i++) {
    if (data[i][0] === key) {
      sheet.getRange(i + 1, 2).setValue(value);
      sheet.getRange(i + 1, 3).setValue(ts);
      return jsonOut({ success: true });
    }
  }
  sheet.appendRow([key, value, ts]);
  return jsonOut({ success: true });
}

function setMetaBatchAction(items) {
  if (!items || !items.length) return jsonOut({ error: 'Missing items' });
  var sheet = getMetaSheet();
  var data  = sheet.getDataRange().getValues();
  var ts    = new Date();
  var keyRow = {};
  for (var i = 1; i < data.length; i++) keyRow[data[i][0]] = i + 1;
  items.forEach(function(it) {
    if (keyRow[it.key]) {
      sheet.getRange(keyRow[it.key], 2).setValue(it.value);
      sheet.getRange(keyRow[it.key], 3).setValue(ts);
    } else {
      sheet.appendRow([it.key, it.value, ts]);
      keyRow[it.key] = sheet.getLastRow();
    }
  });
  return jsonOut({ success: true });
}


function jsonOut(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function sanitizeFolderName(s) {
  return String(s).replace(/[\/\\:*?"<>|]/g, '_').trim() || 'unknown';
}

function getOrCreateFolder(parent, name) {
  var it = parent.getFoldersByName(name);
  if (it.hasNext()) return it.next();
  return parent.createFolder(name);
}

function guessMime(name) {
  var n = String(name || '').toLowerCase();
  if (n.endsWith('.pdf'))                       return 'application/pdf';
  if (n.endsWith('.pptx'))                      return 'application/vnd.openxmlformats-officedocument.presentationml.presentation';
  if (n.endsWith('.ppt'))                       return 'application/vnd.ms-powerpoint';
  if (n.endsWith('.xlsx'))                      return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
  if (n.endsWith('.xls'))                       return 'application/vnd.ms-excel';
  if (n.endsWith('.docx'))                      return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
  if (n.endsWith('.doc'))                       return 'application/msword';
  if (n.endsWith('.csv'))                       return 'text/csv';
  if (n.endsWith('.html') || n.endsWith('.htm'))return 'text/html';
  if (n.endsWith('.png'))                       return 'image/png';
  if (n.endsWith('.jpg') || n.endsWith('.jpeg'))return 'image/jpeg';
  if (n.endsWith('.gif'))                       return 'image/gif';
  if (n.endsWith('.webp'))                      return 'image/webp';
  if (n.endsWith('.bmp'))                       return 'image/bmp';
  return 'application/octet-stream';
}

function toHtml(text) {
  return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
}

function getLogSheet(ss) {
  var log = ss.getSheetByName('Email Log');
  if (!log) { log = ss.insertSheet('Email Log'); log.appendRow(['Timestamp','Batch','Tab','Recipient','Subject','Status']); }
  return log;
}

function fillDownBatch(data, batchIdx) {
  var lastBatch = '';
  return data.slice(1).filter(function(r) { return r.some(function(c) { return c !== ''; }); }).map(function(r) {
    var row = r.slice();
    if (batchIdx >= 0) {
      if (String(row[batchIdx]).trim() !== '') lastBatch = row[batchIdx];
      else if (lastBatch) row[batchIdx] = lastBatch;
    }
    return row;
  });
}

function signature() {
  return '\n\nDr.Sriharikrishnaa S,\nMolecular Biologist,\nDepartment of Clinical Genetics,\nAnderson Diagnostics Services Private Limited,\nKilpauk,Chennai- 600010\nPh:9566726255\nORCD ID:https://orcid.org/0000-0003-2001-383X';
}

function signatureHtml() {
  return '<br><br>Dr.Sriharikrishnaa S,<br>Molecular Biologist,<br>Department of Clinical Genetics,<br>Anderson Diagnostics Services Private Limited,<br>Kilpauk,Chennai- 600010<br>Ph:9566726255<br>ORCD ID:<a href="https://orcid.org/0000-0003-2001-383X">https://orcid.org/0000-0003-2001-383X</a>';
}

function normalizeHeader(name) {
  return String(name || '').toLowerCase().replace(/\s+/g, '');
}

function findHeaderIndex(headers, keyword) {
  keyword = String(keyword || '').toLowerCase().replace(/\s+/g, '');
  return headers.findIndex(function(h) {
    return normalizeHeader(h).indexOf(keyword) !== -1;
  });
}

function findMailHeaderIndex(headers) {
  return headers.findIndex(function(h) {
    var n = normalizeHeader(h);
    return n.indexOf('mail') !== -1 || n.indexOf('email') !== -1;
  });
}

function isBatchMailAlreadySent(batch) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheets = ss.getSheets();
  for (var s = 0; s < sheets.length; s++) {
    var sheet = sheets[s];
    var name = sheet.getName();
    if (name === META_SHEET_NAME || name === 'Email Log') continue;
    var data = sheet.getDataRange().getValues();
    if (!data || data.length < 2) continue;
    var headers = data[0];
    var batchIdx = findHeaderIndex(headers, 'batch');
    var mailIdx = findMailHeaderIndex(headers);
    if (batchIdx < 0 || mailIdx < 0) continue;
    for (var i = 1; i < data.length; i++) {
      if (String(data[i][batchIdx] || '').trim() === batch) {
        var statusCell = String(data[i][mailIdx] || '').toLowerCase();
        if (statusCell.indexOf('sent') !== -1 || statusCell.indexOf('mail sent') !== -1) {
          return true;
        }
      }
    }
  }
  return false;
}

function markBatchMailStatus(batch, status) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheets = ss.getSheets();
  for (var s = 0; s < sheets.length; s++) {
    var sheet = sheets[s];
    var name = sheet.getName();
    if (name === META_SHEET_NAME || name === 'Email Log') continue;
    var data = sheet.getDataRange().getValues();
    if (!data || data.length < 1) continue;
    var headers = data[0];
    var batchIdx = findHeaderIndex(headers, 'batch');
    if (batchIdx < 0) continue;
    var mailIdx = findMailHeaderIndex(headers);
    if (mailIdx < 0) {
      mailIdx = headers.length;
      sheet.getRange(1, mailIdx + 1).setValue('Mail Status');
      headers.push('Mail Status');
    }
    var colValues = [];
    for (var i = 1; i < data.length; i++) {
      var current = String(data[i][mailIdx] || '');
      if (String(data[i][batchIdx] || '').trim() === batch) {
        colValues.push([status]);
      } else {
        colValues.push([current]);
      }
    }
    if (colValues.length > 0) {
      sheet.getRange(2, mailIdx + 1, colValues.length, 1).setValues(colValues);
    }
  }
}

function setBatchMailSentMeta(batch, prefix) {
  if (!batch || !prefix) return;
  setMetaAction(prefix + batch, String(new Date()));
}

function getMetaValue(key) {
  var sheet = getMetaSheet();
  var data = sheet.getDataRange().getValues();
  for (var i = 1; i < data.length; i++) {
    if (data[i][0] === key) return String(data[i][1]);
  }
  return null;
}


function sendDNARNAEmail(batch, pptBase64, pptName, customSubject, customBody, to, cc) {
  var ss = SpreadsheetApp.getActiveSpreadsheet(), sheet = getDataSheet();
  var data = sheet.getDataRange().getDisplayValues(), headers = data[0];
  var col = function(kw) { return headers.findIndex(function(h) { return h.toLowerCase().replace(/\s+/g,'').includes(kw.toLowerCase().replace(/\s+/g,'')); }); };
  var batchIdx = col('batch'), receivedIdx = col('receiveddate'), tatIdx = col('tat');
  var sampleTypeIdx = col('sampletype'), sampleNumIdx = col('samplenumber'), qcStatusIdx = col('qcstatus');
  var allRows = fillDownBatch(data, batchIdx);
  var batchRows = allRows.filter(function(r) { return String(r[batchIdx]||'').trim() === batch; });
  if (batchRows.length === 0) return jsonOut({ error: 'No data for ' + batch });
  var total = batchRows.length;
  var submissionDate = receivedIdx >= 0 ? batchRows[0][receivedIdx] : '';
  var tatDate = tatIdx >= 0 ? batchRows[0][tatIdx] : '';
  var variantCount = batchRows.filter(function(r) { return sampleTypeIdx >= 0 ? String(r[sampleTypeIdx]).toUpperCase().includes('DNA') : String(r[sampleNumIdx]||'').includes('MP'); }).length;
  var fusionCount  = batchRows.filter(function(r) { return sampleTypeIdx >= 0 ? String(r[sampleTypeIdx]).toUpperCase().includes('RNA') : String(r[sampleNumIdx]||'').includes('FG'); }).length;
  var pad = function(n) { return String(n).padStart(2,'0'); };
  var failedSamples = qcStatusIdx >= 0 ? batchRows.filter(function(r) { var v = String(r[qcStatusIdx]||'').trim().toLowerCase(); return v==='fail'||v==='failed'||(v!==''&&!v.includes('pass')); }) : [];
  var qcPlainLine = failedSamples.length===0 ? 'All Samples : QC Passed' : failedSamples.map(function(r) { return (sampleNumIdx>=0?r[sampleNumIdx]:'Sample')+' is failed. Therefore taken for reanalysis'; }).join('\n');
  var qcHtmlLine  = failedSamples.length===0 ? 'All Samples : QC Passed' : failedSamples.map(function(r) { return '<span style="color:red;font-weight:bold">'+(sampleNumIdx>=0?r[sampleNumIdx]:'Sample')+' is failed. Therefore taken for reanalysis</span>'; }).join('<br>');
  var subject   = batch + ' sample information';
  var plainBody = 'Dear team,\nDNA samples were received from Department of Haematology , CMC Vellore. Quality Control assessment was performed using Qubit and sample order is attached as PDF.\n\nSubmission Date: '+submissionDate+'\nPanel Name/Kit Type: Myeloid ARCHER Variant Plex , FUSION Plex\n\nTotal Samples Received: '+total+'\nMyeloid ARCHER Variant Plex - '+pad(variantCount)+'\nFUSION Plex - '+pad(fusionCount)+'\n'+qcPlainLine+'\n\nLibrary sample order , concentration and pooled library tapestation profiles will be shared by '+tatDate+' .';
  var htmlBody  = '<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.8;color:#222;"><p>Dear team,</p><p>DNA samples were received from Department of Haematology , CMC Vellore. Quality Control assessment was performed using Qubit and sample order is attached as PDF.</p><p>Submission Date: '+submissionDate+'<br>Panel Name/Kit Type: Myeloid ARCHER Variant Plex , FUSION Plex</p><p>Total Samples Received: '+total+'<br>Myeloid ARCHER Variant Plex - '+pad(variantCount)+'<br>FUSION Plex - '+pad(fusionCount)+'<br>'+qcHtmlLine+'</p><p>Library sample order , concentration and pooled library tapestation profiles will be shared by '+tatDate+' .</p></div>';
  var mailKey = 'mailSent_' + batch;
  if (getMetaValue(mailKey)) return jsonOut({ success:true, message: 'Email already sent for ' + batch });
  var opts = { to: to || MAIL_TO, subject:customSubject||subject, body:customBody||plainBody, htmlBody:customBody?('<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.8;">'+toHtml(customBody)+'</div>'):htmlBody };
  if (cc) opts.cc = cc;
  if (pptBase64&&pptName) { var m=pptName.toLowerCase().endsWith('.pdf')?'application/pdf':'application/vnd.openxmlformats-officedocument.presentationml.presentation'; opts.attachments=[Utilities.newBlob(Utilities.base64Decode(pptBase64),m,pptName)]; }
  try {
    MailApp.sendEmail(opts);
  } catch (err) {
    return jsonOut({ error: 'Mail send failed: ' + (err.message || String(err)) });
  }
  setBatchMailSentMeta(batch, 'mailSent_');
  markBatchMailStatus(batch, 'Mail sent');
  getLogSheet(ss).appendRow([new Date().toLocaleString(),batch,'DNA & RNA Status',opts.to,opts.subject,pptBase64?'Sent with PPT':'Sent']);
  return jsonOut({ success:true });
}

function sendLibraryPrepEmail(batch, pptBase64, pptName, customSubject, customBody, to, cc) {
  var ss = SpreadsheetApp.getActiveSpreadsheet(), sheet = getDataSheet();
  var data = sheet.getDataRange().getDisplayValues(), headers = data[0];
  var col = function(kw) { return headers.findIndex(function(h) { return h.toLowerCase().replace(/\s+/g,'').includes(kw.toLowerCase().replace(/\s+/g,'')); }); };
  var batchIdx = col('batch'), libDateIdx = col('libraryqc');
  var allRows = fillDownBatch(data, batchIdx);
  var batchRows = allRows.filter(function(r) { return String(r[batchIdx]||'').trim() === batch; });
  if (batchRows.length === 0) return jsonOut({ error:'No data for '+batch });
  var libDate = libDateIdx>=0 ? batchRows[0][libDateIdx] : '';
  var subject = 'Regarding library QC and tapestation profile -'+batch;
  var plainBody = 'Dear Team,\nPlease find attached the library concentration and TapeStation QC report for '+batch+' (dated '+libDate+').\nThe report includes:\n\n• Library concentration details\n• Individual sample concentrations for DNA Myeloid , RNA Fusion panel\n• TapeStation QC profiles for all pooled libraries using:\n  • D1000 ScreenTape assay (DNA libraries)\n  • High sensitivity RNA ScreenTape assay (RNA Libraries)\n\nAll pooled libraries have passed QC criteria and are suitable for downstream sequencing.';
  var htmlBody = '<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.8;color:#222;"><p>Dear Team,</p><p>Please find attached the library concentration and TapeStation QC report for <b>'+batch+'</b> (dated '+libDate+').</p><p>The report includes:</p><ul><li>Library concentration details</li><li>Individual sample concentrations for DNA Myeloid , RNA Fusion panel</li><li>TapeStation QC profiles for all pooled libraries using:<ul><li>D1000 ScreenTape assay (DNA libraries)</li><li>High sensitivity RNA ScreenTape assay (RNA Libraries)</li></ul></li></ul><p>All pooled libraries have <b>passed QC criteria</b> and are suitable for downstream sequencing.</p></div>';
  var mailKey = 'mailSentLib_' + batch;
  if (getMetaValue(mailKey)) return jsonOut({ success:true, message: 'Email already sent for ' + batch });
  var opts = { to: to || MAIL_TO, subject:customSubject||subject, body:customBody||plainBody, htmlBody:customBody?('<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.8;">'+toHtml(customBody)+'</div>'):htmlBody };
  if (cc) opts.cc = cc;
  if (pptBase64&&pptName) { var m=pptName.toLowerCase().endsWith('.pdf')?'application/pdf':'application/vnd.openxmlformats-officedocument.presentationml.presentation'; opts.attachments=[Utilities.newBlob(Utilities.base64Decode(pptBase64),m,pptName)]; }
  try {
    MailApp.sendEmail(opts);
  } catch (err) {
    return jsonOut({ error: 'Mail send failed: ' + (err.message || String(err)) });
  }
  setBatchMailSentMeta(batch, 'mailSentLib_');
  markBatchMailStatus(batch, 'Mail sent');
  getLogSheet(ss).appendRow([new Date().toLocaleString(),batch,'Library Preparation',opts.to,opts.subject,pptBase64?'Sent with PPT':'Sent']);
  return jsonOut({ success:true });
}

function sendDataTransferEmail(batch, customSubject, customBody, files, fileIds, to, cc) {
  var ss = SpreadsheetApp.getActiveSpreadsheet(), sheet = getDataSheet();
  var data = sheet.getDataRange().getDisplayValues(), headers = data[0];
  var col = function(kw) { return headers.findIndex(function(h) { return h.toLowerCase().replace(/\s+/g,'').includes(kw.toLowerCase().replace(/\s+/g,'')); }); };
  var batchIdx = col('batch'), dtDateIdx = col('transferringdata');
  var allRows = fillDownBatch(data, batchIdx);
  var batchRows = allRows.filter(function(r) { return String(r[batchIdx]||'').trim() === batch; });
  if (batchRows.length === 0) return jsonOut({ error:'No data for '+batch });
  var dtDate = dtDateIdx>=0 ? batchRows[0][dtDateIdx] : '';
  var subject = 'Regarding '+batch+' fastq and QC result files';
  var plain = customBody || ('Dear Team,\n\nGreetings of the day,\n\nPlease find the '+batch+' sequencing data and QC report shared through Filezilla for the following:\n\nFilezilla Credentials:\n\nHostname: 123.176.34.25\nPort: 6621\nUser: client4\nPassword: Bioinfo@567\nFile Protocol: FTP\n\n\nFolder(s) for '+batch+' sequencing data:\n'+dtDate+'\n\nNote: We strongly recommend using Filezilla FTP client to download the files.\n\nPlease find attached the SOP for downloading files via FileZilla for your reference.\n\nPlease note that these files will be available for download for 10 days from the date of this email, after which they will be automatically deleted.');
  var htmlB = customBody ? ('<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.8;">'+toHtml(customBody)+'</div>') : ('<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.8;color:#222;"><p>Dear Team,</p><p>Greetings of the day,</p><p>Please find the <b>'+batch+'</b> sequencing data and QC report shared through Filezilla for the following:</p><p><b>Filezilla Credentials:</b><br>Hostname: 123.176.34.25<br>Port: 6621<br>User: client4<br>Password: Bioinfo@567<br>File Protocol: FTP</p><p><b>Folder(s) for '+batch+' sequencing data:</b><br>'+dtDate+'</p><p><i>Note: We strongly recommend using Filezilla FTP client to download the files.</i></p><p>Please find attached the SOP for downloading files via FileZilla for your reference.</p><p>Please note that these files will be available for download for <b>10 days</b> from the date of this email, after which they will be automatically deleted.</p></div>');
  var opts = { to: to || MAIL_TO, subject:customSubject||subject, body:plain, htmlBody:htmlB };
  if (cc) opts.cc = cc;
  var attachments = [];
  if (fileIds && fileIds.length > 0) {
    fileIds.forEach(function(id) {
      try { attachments.push(DriveApp.getFileById(id).getBlob()); } catch(e) {}
    });
  } else if (files && files.length > 0) {
    attachments = files.map(function(f) { var ext=f.name.toLowerCase(),mime='application/octet-stream'; if(ext.endsWith('.xlsx')||ext.endsWith('.xls'))mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'; if(ext.endsWith('.html')||ext.endsWith('.htm'))mime='text/html'; if(ext.endsWith('.pdf'))mime='application/pdf'; if(ext.endsWith('.csv'))mime='text/csv'; return Utilities.newBlob(Utilities.base64Decode(f.base64),mime,f.name); });
  }
  if (getMetaValue('mailSentDT_' + batch)) return jsonOut({ success:true, message: 'Email already sent for ' + batch });
  if (attachments.length > 0) opts.attachments = attachments;
  try {
    MailApp.sendEmail(opts);
  } catch (err) {
    return jsonOut({ error: 'Mail send failed: ' + (err.message || String(err)) });
  }
  setBatchMailSentMeta(batch, 'mailSentDT_');
  markBatchMailStatus(batch, 'Mail sent');
  getLogSheet(ss).appendRow([new Date().toLocaleString(),batch,'Data Transfer',opts.to,opts.subject,attachments.length>0?'Sent with '+attachments.length+' file(s)':'Sent']);
  return jsonOut({ success:true });
}

function sendDataUploadEmail(batch, customSubject, customBody, files, fileIds, to, cc) {
  if (!batch) return jsonOut({ error: 'Missing batch' });
  if (isBatchMailAlreadySent(batch)) {
    markBatchMailStatus(batch, 'Mail sent');
    return jsonOut({ success: true, message: 'Email already sent for ' + batch });
  }
  var subject = customSubject || (batch + ' -Data uploaded in cloud based platform');
  var mainText = customBody || ('Dear Hematology team,\nGreetings of the day,\nPlease find the snippet confirming the VARIANTPLEX, FUSIONPLEX data uploaded to cloud based platform ARCHER ANALYSIS - ' + batch + ' . Please access the data .');
  var plainBody = mainText + '\n\nThank you' + signature();
  var inlineImages = {};
  var imgHtml = '';
  if (files && files.length > 0) {
    files.forEach(function(f, i) {
      var ext = f.name.toLowerCase(), mime = 'image/jpeg';
      if (ext.endsWith('.png'))  mime = 'image/png';
      if (ext.endsWith('.gif'))  mime = 'image/gif';
      if (ext.endsWith('.webp')) mime = 'image/webp';
      if (ext.endsWith('.bmp'))  mime = 'image/bmp';
      var key = 'duimg' + i;
      inlineImages[key] = Utilities.newBlob(Utilities.base64Decode(f.base64), mime, f.name);
      imgHtml += '<br><img src="cid:' + key + '" style="max-width:100%;display:block;margin:8px 0;">';
    });
  }
  var attachments = [];
  if (fileIds && fileIds.length > 0) {
    fileIds.forEach(function(id) {
      try {
        attachments.push(DriveApp.getFileById(id).getBlob());
      } catch (e) {
      }
    });
  }
  var mailKey = 'mailSentDU_' + batch;
  if (getMetaValue(mailKey)) return jsonOut({ success:true, message: 'Email already sent for ' + batch });
  var htmlBody = '<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.8;color:#222;">' + toHtml(mainText) + imgHtml + '<br><br>Thank you' + signatureHtml() + '</div>';
  var opts = { to: to || MAIL_TO, subject: subject, body: plainBody, htmlBody: htmlBody };
  if (cc) opts.cc = cc;
  if (Object.keys(inlineImages).length > 0) opts.inlineImages = inlineImages;
  if (attachments.length > 0) opts.attachments = attachments;
  try {
    MailApp.sendEmail(opts);
  } catch (err) {
    return jsonOut({ error: 'Mail send failed: ' + (err.message || String(err)) });
  }
  setBatchMailSentMeta(batch, 'mailSentDU_');
  markBatchMailStatus(batch, 'Mail sent');
  getLogSheet(SpreadsheetApp.getActiveSpreadsheet()).appendRow([new Date().toLocaleString(), batch, 'Data Upload', opts.to, subject, (attachments.length > 0 ? 'Sent with ' + attachments.length + ' attachment(s)' : '') + (Object.keys(inlineImages).length > 0 ? (attachments.length > 0 ? ', ' : '') + 'Sent with ' + Object.keys(inlineImages).length + ' image(s)' : 'Sent')]);
  return jsonOut({ success: true });
}
