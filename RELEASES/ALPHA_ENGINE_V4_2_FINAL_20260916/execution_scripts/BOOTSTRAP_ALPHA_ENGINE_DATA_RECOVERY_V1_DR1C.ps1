$ErrorActionPreference = "Stop"

$ROOT = "C:\Users\santi\OneDrive\Escritorio\ALPHA_ENGINE_PRODUCTION"
$V13  = Join-Path $ROOT "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
$REC  = Join-Path $ROOT "ALPHA_ENGINE_DATA_RECOVERY_V1"

Write-Host "============================================================"
Write-Host "ALPHA ENGINE"
Write-Host "DATA RECOVERY V1 - DR1-C"
Write-Host "RECOVERED V8 UNIVERSE + FULL DATA STAGING PAYLOADS"
Write-Host "RAW DATA ONLY / ALL V8-V10 SCORE COLUMNS FORCED BLANK"
Write-Host "NO SHEETS / WEB / PRODUCT STATE / V13 MUTATION"
Write-Host "============================================================"

if (-not (Test-Path $REC)) { throw "No existe Recovery V1: $REC" }
if (-not (Test-Path $V13)) { throw "No existe V13: $V13" }

New-Item -ItemType Directory -Force -Path (Join-Path $REC "config") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $REC "src\alpha_data_recovery") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $REC "scripts") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $REC "tests") | Out-Null

Set-Location $ROOT
$before = git status --porcelain -- "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"

# Recovered from the real V8 workbook. No scores or stale output values included.
$u64 = @'
77u/Y2Fub25pY2FsX3RpY2tlcixhc3NldF9jbGFzcyxtb3RvcixzZWN0b3IsYmVuY2htYXJrLG1hcmtldF9zeW1ib2wsZnVuZGFtZW50YWxzX3N5bWJvbCxzZWNfdGlja2VyLGNvdW50cnksYWN0aXZlLG5vdGUKTVNGVCxDRURFQVIsRnVuZGFtZW50YWwsVGVjbm9sb2dpY28sWExLLE1TRlQsTVNGVCxNU0ZULEV4dGVyaW9yLFNJLApCUkstQixDRURFQVIsRnVuZGFtZW50YWwsRmluYW5jaWVybyxYTEYsQlJLLUIsQlJLLUIsQlJLLUIsRXh0ZXJpb3IsU0ksClBHLENFREVBUixGdW5kYW1lbnRhbCxDb25zdW1vIE1hc2l2byxYTFAsUEcsUEcsUEcsRXh0ZXJpb3IsU0ksCk1FTEksQ0VERUFSLEZ1bmRhbWVudGFsLFRlY25vbG9naWNvLFhMSyxNRUxJLE1FTEksTUVMSSxFeHRlcmlvcixTSSwKTUVUQSxDRURFQVIsRnVuZGFtZW50YWwsQ29tdW5pY2FjaW9uLFhMQyxNRVRBLE1FVEEsTUVUQSxFeHRlcmlvcixTSSwKQVZHTyxDRURFQVIsRnVuZGFtZW50YWwsSUEgLyBTZW1pY29uZHVjdG9yZXMsU01ILEFWR08sQVZHTyxBVkdPLEV4dGVyaW9yLFNJLApBTVpOLENFREVBUixGdW5kYW1lbnRhbCxDb25zdW1vIERpc2NyZWNpb25hbCxYTFksQU1aTixBTVpOLEFNWk4sRXh0ZXJpb3IsU0ksCkdFLENFREVBUixGdW5kYW1lbnRhbCxJbmR1c3RyaWFsLFhMSSxHRSxHRSxHRSxFeHRlcmlvcixTSSwKTktFLENFREVBUixGdW5kYW1lbnRhbCxDb25zdW1vIERpc2NyZWNpb25hbCxYTFksTktFLE5LRSxOS0UsRXh0ZXJpb3IsU0ksCkRJUyxDRURFQVIsRnVuZGFtZW50YWwsQ29tdW5pY2FjaW9uLFhMQyxESVMsRElTLERJUyxFeHRlcmlvcixTSSwKQ0FULENFREVBUixGdW5kYW1lbnRhbCxJbmR1c3RyaWFsLFhMSSxDQVQsQ0FULENBVCxFeHRlcmlvcixTSSwKTU1NLENFREVBUixGdW5kYW1lbnRhbCxJbmR1c3RyaWFsLFhMSSxNTU0sTU1NLE1NTSxFeHRlcmlvcixTSSwKUEZFLENFREVBUixGdW5kYW1lbnRhbCxTYWx1ZCxYTFYsUEZFLFBGRSxQRkUsRXh0ZXJpb3IsU0ksClYsQ0VERUFSLEZ1bmRhbWVudGFsLEZpbmFuY2llcm8sWExGLFYsVixWLEV4dGVyaW9yLFNJLApBWFAsQ0VERUFSLEZ1bmRhbWVudGFsLEZpbmFuY2llcm8sWExGLEFYUCxBWFAsQVhQLEV4dGVyaW9yLFNJLApDQUFQLENFREVBUixGdW5kYW1lbnRhbCxJbmR1c3RyaWFsLFhMSSxDQUFQLENBQVAsQ0FBUCxFeHRlcmlvcixTSSwKQUJCVixDRURFQVIsRnVuZGFtZW50YWwsU2FsdWQsWExWLEFCQlYsQUJCVixBQkJWLEV4dGVyaW9yLFNJLApCQUJBLENFREVBUixGdW5kYW1lbnRhbCxDb25zdW1vIERpc2NyZWNpb25hbCxYTFksQkFCQSxCQUJBLEJBQkEsRXh0ZXJpb3IsU0ksCkNPSU4sQ0VERUFSLEFsdGVybmF0aXZvLENyaXB0byxCVEMtVVNELENPSU4sQ09JTixDT0lOLEV4dGVyaW9yLFNJLApORkxYLENFREVBUixGdW5kYW1lbnRhbCxDb211bmljYWNpb24sWExDLE5GTFgsTkZMWCxORkxYLEV4dGVyaW9yLFNJLApHTE9CLENFREVBUixGdW5kYW1lbnRhbCxUZWNub2xvZ2ljbyxYTEssR0xPQixHTE9CLEdMT0IsRXh0ZXJpb3IsU0ksCkJBLENFREVBUixGdW5kYW1lbnRhbCxJbmR1c3RyaWFsLFhMSSxCQSxCQSxCQSxFeHRlcmlvcixTSSwKTlUsQ0VERUFSLEZ1bmRhbWVudGFsLEZpbmFuY2llcm8sWExGLE5VLE5VLE5VLEV4dGVyaW9yLFNJLApDSUJSLEVURixBbHRlcm5hdGl2byxUZWNub2xvZ2ljbyxRUVEsQ0lCUixDSUJSLENJQlIsRXh0ZXJpb3IsU0ksCk9SQ0wsQ0VERUFSLEZ1bmRhbWVudGFsLFRlY25vbG9naWNvLFhMSyxPUkNMLE9SQ0wsT1JDTCxFeHRlcmlvcixTSSwKTlZEQSxDRURFQVIsRnVuZGFtZW50YWwsSUEgLyBTZW1pY29uZHVjdG9yZXMsU01ILE5WREEsTlZEQSxOVkRBLEV4dGVyaW9yLFNJLApUU00sQ0VERUFSLEZ1bmRhbWVudGFsLElBIC8gU2VtaWNvbmR1Y3RvcmVzLFNNSCxUU00sVFNNLFRTTSxFeHRlcmlvcixTSSwKRVRIQSxFVEYsQWx0ZXJuYXRpdm8sQ3JpcHRvLEVUSC1VU0QsRVRIQSxFVEhBLEVUSEEsRXh0ZXJpb3IsU0ksCkFNRCxDRURFQVIsRnVuZGFtZW50YWwsSUEgLyBTZW1pY29uZHVjdG9yZXMsU01ILEFNRCxBTUQsQU1ELEV4dGVyaW9yLFNJLApBU01MLENFREVBUixGdW5kYW1lbnRhbCxJQSAvIFNlbWljb25kdWN0b3JlcyxTTUgsQVNNTCxBU01MLEFTTUwsRXh0ZXJpb3IsU0ksCkxBUixDRURFQVIsRnVuZGFtZW50YWwsTWF0ZXJpYWxlcyxYTEIsTEFSLExBUixMQVIsRXh0ZXJpb3IsU0ksClNILEVURixBbHRlcm5hdGl2byxEaXZlcnNpZmljYWRvIChFVEYpLFNQWSxTSCxTSCxTSCxFeHRlcmlvcixTSSwKR0xELEVURixBbHRlcm5hdGl2byxPdHJvLFNQWSxHTEQsR0xELEdMRCxFeHRlcmlvcixTSSwKV01ULENFREVBUixGdW5kYW1lbnRhbCxDb25zdW1vIE1hc2l2byxYTFAsV01ULFdNVCxXTVQsRXh0ZXJpb3IsU0ksClhMRixFVEYsQWx0ZXJuYXRpdm8sRmluYW5jaWVybyxTUFksWExGLFhMRixYTEYsRXh0ZXJpb3IsU0ksClhMSSxFVEYsQWx0ZXJuYXRpdm8sSW5kdXN0cmlhbCxTUFksWExJLFhMSSxYTEksRXh0ZXJpb3IsU0ksClhMRSxFVEYsQWx0ZXJuYXRpdm8sRW5lcmdpYSxTUFksWExFLFhMRSxYTEUsRXh0ZXJpb3IsU0ksClRNLENFREVBUixGdW5kYW1lbnRhbCxDb25zdW1vIERpc2NyZWNpb25hbCxYTFksVE0sVE0sVE0sRXh0ZXJpb3IsU0ksClNPTlksQ0VERUFSLEZ1bmRhbWVudGFsLFRlY25vbG9naWNvLFhMSyxTT05ZLFNPTlksU09OWSxFeHRlcmlvcixTSSwKRVdKLEVURixBbHRlcm5hdGl2byxEaXZlcnNpZmljYWRvIChFVEYpLFNQWSxFV0osRVdKLEVXSixFeHRlcmlvcixTSSwKUEJSLENFREVBUixGdW5kYW1lbnRhbCxFbmVyZ2lhLFhMRSxQQlIsUEJSLFBCUixFeHRlcmlvcixTSSwKQkJELENFREVBUixGdW5kYW1lbnRhbCxGaW5hbmNpZXJvLFhMRixCQkQsQkJELEJCRCxFeHRlcmlvcixTSSwKU0lELENFREVBUixGdW5kYW1lbnRhbCxNYXRlcmlhbGVzLFhMQixTSUQsU0lELFNJRCxFeHRlcmlvcixTSSwKVkFMRSxDRURFQVIsRnVuZGFtZW50YWwsTWF0ZXJpYWxlcyxYTEIsVkFMRSxWQUxFLFZBTEUsRXh0ZXJpb3IsU0ksCkFSS0ssRVRGLEFsdGVybmF0aXZvLERpdmVyc2lmaWNhZG8gKEVURiksU1BZLEFSS0ssQVJLSyxBUktLLEV4dGVyaW9yLFNJLApFRU0sRVRGLEFsdGVybmF0aXZvLERpdmVyc2lmaWNhZG8gKEVURiksU1BZLEVFTSxFRU0sRUVNLEV4dGVyaW9yLFNJLApFV1osRVRGLEFsdGVybmF0aXZvLERpdmVyc2lmaWNhZG8gKEVURiksU1BZLEVXWixFV1osRVdaLEV4dGVyaW9yLFNJLApBUk0sQ0VERUFSLEZ1bmRhbWVudGFsLElBIC8gU2VtaWNvbmR1Y3RvcmVzLFNNSCxBUk0sQVJNLEFSTSxFeHRlcmlvcixTSSwKVFhBUixBY2Npw7NuLEZ1bmRhbWVudGFsLE1hdGVyaWFsZXMsXk1FUlYsVFhBUi5CQSxUWEFSLkJBLCxBcmdlbnRpbmEsU0ksClBBTVAsQWNjacOzbixGdW5kYW1lbnRhbCxFbmVyZ2lhLF5NRVJWLFBBTVAuQkEsUEFNLFBBTSxBcmdlbnRpbmEsU0ksVGlja2VyIG1hZXN0cm8gw7puaWNvOyBmdW5kYW1lbnRhbGVzL1NFQyB2w61hIFBBTS4KQ0VQVSxBY2Npw7NuLEZ1bmRhbWVudGFsLEVuZXJnaWEsXk1FUlYsQ0VQVS5CQSxDRVBVLENFUFUsQXJnZW50aW5hLFNJLApFQ09HLEFjY2nDs24sRnVuZGFtZW50YWwsRW5lcmdpYSxeTUVSVixFQ09HLkJBLEVDT0cuQkEsLEFyZ2VudGluYSxTSSwKQ1ZYLENFREVBUixGdW5kYW1lbnRhbCxFbmVyZ2lhLFhMRSxDVlgsQ1ZYLENWWCxFeHRlcmlvcixTSSwKQUFQTCxDRURFQVIsRnVuZGFtZW50YWwsVGVjbm9sb2dpY28sWExLLEFBUEwsQUFQTCxBQVBMLEV4dGVyaW9yLFNJLApTUENYLENFREVBUixGdW5kYW1lbnRhbCxJbmR1c3RyaWFsLFhMSSxTUENYLFNQQ1gsU1BDWCxFeHRlcmlvcixTSSwKR09PR0wsQ0VERUFSLEZ1bmRhbWVudGFsLFRlY25vbG9naWNvLFhMSyxHT09HTCxHT09HTCxHT09HTCxFeHRlcmlvcixTSSwKTVUsQ0VERUFSLEZ1bmRhbWVudGFsLElBIC8gU2VtaWNvbmR1Y3RvcmVzLFNNSCxNVSxNVSxNVSxFeHRlcmlvcixTSSwKQUNOLENFREVBUixGdW5kYW1lbnRhbCxPdHJvLFNQWSxBQ04sQUNOLEFDTixFeHRlcmlvcixTSSwKQ09TVCxDRURFQVIsRnVuZGFtZW50YWwsQ29uc3VtbyBNYXNpdm8sWExQLENPU1QsQ09TVCxDT1NULEV4dGVyaW9yLFNJLApMTFksQ0VERUFSLEZ1bmRhbWVudGFsLFNhbHVkLFhMVixMTFksTExZLExMWSxFeHRlcmlvcixTSSwKVFNMQSxDRURFQVIsRnVuZGFtZW50YWwsVGVjbm9sb2dpY28sWExLLFRTTEEsVFNMQSxUU0xBLEV4dGVyaW9yLFNJLApWSVNULENFREVBUixGdW5kYW1lbnRhbCxFbmVyZ2lhLFhMRSxWSVNULFZJU1QsVklTVCxFeHRlcmlvcixTSSwKWVBGLEFjY2nDs24sRnVuZGFtZW50YWwsRW5lcmdpYSxeTUVSVixZUEZELkJBLFlQRixZUEYsQXJnZW50aW5hLFNJLApCWU1BLkJBLEFjY2nDs24sRnVuZGFtZW50YWwsRmluYW5jaWVybyxeTUVSVixCWU1BLkJBLEJZTUEuQkEsLEFyZ2VudGluYSxTSSwKUEFOVyxDRURFQVIsRnVuZGFtZW50YWwsVGVjbm9sb2dpY28sWExLLFBBTlcsUEFOVyxQQU5XLEV4dGVyaW9yLFNJLApLRUVMLENFREVBUixBbHRlcm5hdGl2byxPdHJvLEJUQy1VU0QsS0VFTCxLRUVMLEtFRUwsRXh0ZXJpb3IsU0ksVGlja2VyIGFjdHVhbGl6YWRvOiBCSVRGIOKGkiBLRUVMLgpCUEM3RCxCb25vLFJlbnRhIEZpamEsQk9OT1MgSEQsLEJQQzdELEJQQzdELEJQQzdELEV4dGVyaW9yLFNJLApCUEQ3RCxCb25vLFJlbnRhIEZpamEsQk9OT1MgSEQsLEJQRDdELEJQRDdELEJQRDdELEV4dGVyaW9yLFNJLApHRDMwRCxCb25vLFJlbnRhIEZpamEsQk9OT1MgSEQsLEdEMzBELEdEMzBELEdEMzBELEV4dGVyaW9yLFNJLApBTDMwRCxCb25vLFJlbnRhIEZpamEsQk9OT1MgSEQsLEFMMzBELEFMMzBELEFMMzBELEV4dGVyaW9yLFNJLApBTDM1RCxCb25vLFJlbnRhIEZpamEsQk9OT1MgSEQsLEFMMzVELEFMMzVELEFMMzVELEV4dGVyaW9yLFNJLApHRDM4RCxCb25vLFJlbnRhIEZpamEsQk9OT1MgSEQsLEdEMzhELEdEMzhELEdEMzhELEV4dGVyaW9yLFNJLApHRDQxRCxCb25vLFJlbnRhIEZpamEsQk9OT1MgSEQsLEdENDFELEdENDFELEdENDFELEV4dGVyaW9yLFNJLApQTlhDRCxPTixSZW50YSBGaWphLE9OcywsUE5YQ0QsUE5YQ0QsUE5YQ0QsRXh0ZXJpb3IsU0ksClBMQzRELE9OLFJlbnRhIEZpamEsT05zLCxQTEM0RCxQTEM0RCxQTEM0RCxFeHRlcmlvcixTSSwKVlNDVkQsT04sUmVudGEgRmlqYSxPTnMsLFZTQ1ZELFZTQ1ZELFZTQ1ZELEV4dGVyaW9yLFNJLApZTTM0RCxPTixSZW50YSBGaWphLE9OcywsWU0zNEQsWU0zNEQsWU0zNEQsRXh0ZXJpb3IsU0ksCllNQ1hELE9OLFJlbnRhIEZpamEsT05zLCxZTUNYRCxZTUNYRCxZTUNYRCxFeHRlcmlvcixTSSwKSVJDUEQsT04sUmVudGEgRmlqYSxPTnMsLElSQ1BELElSQ1BELElSQ1BELEV4dGVyaW9yLFNJLApSVUNERCxPTixSZW50YSBGaWphLE9OcywsUlVDREQsUlVDREQsUlVDREQsRXh0ZXJpb3IsU0ksClJVQ0VELE9OLFJlbnRhIEZpamEsT05zLCxSVUNFRCxSVUNFRCxSVUNFRCxFeHRlcmlvcixTSSwKVExDTUQsT04sUmVudGEgRmlqYSxPTnMsLFRMQ01ELFRMQ01ELFRMQ01ELEV4dGVyaW9yLFNJLApUTENQRCxPTixSZW50YSBGaWphLE9OcywsVExDUEQsVExDUEQsVExDUEQsRXh0ZXJpb3IsU0ksClRMQ1RELE9OLFJlbnRhIEZpamEsT05zLCxUTENURCxUTENURCxUTENURCxFeHRlcmlvcixTSSwKRE5DQUQsT04sUmVudGEgRmlqYSxPTnMsLEROQ0FELEROQ0FELEROQ0FELEV4dGVyaW9yLFNJLApWU0NQRCxPTixSZW50YSBGaWphLE9OcywsVlNDUEQsVlNDUEQsVlNDUEQsRXh0ZXJpb3IsU0ksCkNTNDdELE9OLFJlbnRhIEZpamEsT05zLCxDUzQ3RCxDUzQ3RCxDUzQ3RCxFeHRlcmlvcixTSSwKSVJDT0QsT04sUmVudGEgRmlqYSxPTnMsLElSQ09ELElSQ09ELElSQ09ELEV4dGVyaW9yLFNJLApaWkMxRCxPTixSZW50YSBGaWphLE9OcywsWlpDMUQsWlpDMUQsWlpDMUQsRXh0ZXJpb3IsU0ksCllNMzlELE9OLFJlbnRhIEZpamEsT05zLCxZTTM5RCxZTTM5RCxZTTM5RCxFeHRlcmlvcixTSSwKQU8yN0QsQm9ubyxSZW50YSBGaWphLEJPTk9TIEhELCxBTzI3RCxBTzI3RCxBTzI3RCxFeHRlcmlvcixTSSwKQU8yOEQsQm9ubyxSZW50YSBGaWphLEJPTk9TIEhELCxBTzI4RCxBTzI4RCxBTzI4RCxFeHRlcmlvcixTSSwKR0QyOUQsQm9ubyxSZW50YSBGaWphLEJPTk9TIEhELCxHRDI5RCxHRDI5RCxHRDI5RCxFeHRlcmlvcixTSSwKQUwyOUQsQm9ubyxSZW50YSBGaWphLEJPTk9TIEhELCxBTDI5RCxBTDI5RCxBTDI5RCxFeHRlcmlvcixTSSwKQURCRSxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsVGVjbm9sb2dpY28sWExLLEFEQkUsQURCRSxBREJFLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKQ1JNLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxUZWNub2xvZ2ljbyxYTEssQ1JNLENSTSxDUk0sRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpJTlRVLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxUZWNub2xvZ2ljbyxYTEssSU5UVSxJTlRVLElOVFUsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpOT1csQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLFRlY25vbG9naWNvLFhMSyxOT1csTk9XLE5PVyxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCklCTSxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsVGVjbm9sb2dpY28sWExLLElCTSxJQk0sSUJNLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKQ1NDTyxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsVGVjbm9sb2dpY28sWExLLENTQ08sQ1NDTyxDU0NPLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKUUNPTSxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsVGVjbm9sb2dpY28sWExLLFFDT00sUUNPTSxRQ09NLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKVFhOLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxUZWNub2xvZ2ljbyxYTEssVFhOLFRYTixUWE4sRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpBREksQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLFRlY25vbG9naWNvLFhMSyxBREksQURJLEFESSxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCkFORVQsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLFRlY25vbG9naWNvLFhMSyxBTkVULEFORVQsQU5FVCxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xClBMVFIsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLFRlY25vbG9naWNvLFhMSyxQTFRSLFBMVFIsUExUUixFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCkNSV0QsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLFRlY25vbG9naWNvLFhMSyxDUldELENSV0QsQ1JXRCxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCkZUTlQsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLFRlY25vbG9naWNvLFhMSyxGVE5ULEZUTlQsRlROVCxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xClNOUFMsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLFRlY25vbG9naWNvLFhMSyxTTlBTLFNOUFMsU05QUyxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCkNETlMsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLFRlY25vbG9naWNvLFhMSyxDRE5TLENETlMsQ0ROUyxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xClJPUCxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsVGVjbm9sb2dpY28sWExLLFJPUCxST1AsUk9QLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKQURTSyxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsVGVjbm9sb2dpY28sWExLLEFEU0ssQURTSyxBRFNLLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKVEVBTSxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsVGVjbm9sb2dpY28sWExLLFRFQU0sVEVBTSxURUFNLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKRERPRyxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsVGVjbm9sb2dpY28sWExLLERET0csRERPRyxERE9HLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKTURCLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxUZWNub2xvZ2ljbyxYTEssTURCLE1EQixNREIsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpJTlRDLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxJQSAvIFNlbWljb25kdWN0b3JlcyxTTUgsSU5UQyxJTlRDLElOVEMsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpMUkNYLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxJQSAvIFNlbWljb25kdWN0b3JlcyxTTUgsTFJDWCxMUkNYLExSQ1gsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpLTEFDLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxJQSAvIFNlbWljb25kdWN0b3JlcyxTTUgsS0xBQyxLTEFDLEtMQUMsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpBTUFULEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxJQSAvIFNlbWljb25kdWN0b3JlcyxTTUgsQU1BVCxBTUFULEFNQVQsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpNUlZMLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxJQSAvIFNlbWljb25kdWN0b3JlcyxTTUgsTVJWTCxNUlZMLE1SVkwsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpNQ0hQLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxJQSAvIFNlbWljb25kdWN0b3JlcyxTTUgsTUNIUCxNQ0hQLE1DSFAsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpOWFBJLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxJQSAvIFNlbWljb25kdWN0b3JlcyxTTUgsTlhQSSxOWFBJLE5YUEksRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpPTixBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsSUEgLyBTZW1pY29uZHVjdG9yZXMsU01ILE9OLE9OLE9OLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKTVBXUixBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsSUEgLyBTZW1pY29uZHVjdG9yZXMsU01ILE1QV1IsTVBXUixNUFdSLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKSlBNLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxGaW5hbmNpZXJvLFhMRixKUE0sSlBNLEpQTSxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCkJBQyxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsRmluYW5jaWVybyxYTEYsQkFDLEJBQyxCQUMsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpXRkMsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLEZpbmFuY2llcm8sWExGLFdGQyxXRkMsV0ZDLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKQyxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsRmluYW5jaWVybyxYTEYsQyxDLEMsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpHUyxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsRmluYW5jaWVybyxYTEYsR1MsR1MsR1MsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpNUyxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsRmluYW5jaWVybyxYTEYsTVMsTVMsTVMsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpCTEssQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLEZpbmFuY2llcm8sWExGLEJMSyxCTEssQkxLLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKU0NIVyxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsRmluYW5jaWVybyxYTEYsU0NIVyxTQ0hXLFNDSFcsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpNQSxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsRmluYW5jaWVybyxYTEYsTUEsTUEsTUEsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpDT0YsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLEZpbmFuY2llcm8sWExGLENPRixDT0YsQ09GLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKQk5ZLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxGaW5hbmNpZXJvLFhMRixCTlksQk5ZLEJOWSxFeHRlcmlvcixTSSxUaWNrZXIgYWN0dWFsaXphZG86IEJLIOKGkiBCTlkuClBOQyxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsRmluYW5jaWVybyxYTEYsUE5DLFBOQyxQTkMsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpVU0IsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLEZpbmFuY2llcm8sWExGLFVTQixVU0IsVVNCLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKU1BHSSxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsRmluYW5jaWVybyxYTEYsU1BHSSxTUEdJLFNQR0ksRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpNQ08sQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLEZpbmFuY2llcm8sWExGLE1DTyxNQ08sTUNPLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKVU5ILEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxTYWx1ZCxYTFYsVU5ILFVOSCxVTkgsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpKTkosQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLFNhbHVkLFhMVixKTkosSk5KLEpOSixFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCk1SSyxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsU2FsdWQsWExWLE1SSyxNUkssTVJLLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKQU1HTixBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsU2FsdWQsWExWLEFNR04sQU1HTixBTUdOLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKR0lMRCxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsU2FsdWQsWExWLEdJTEQsR0lMRCxHSUxELEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKUkVHTixBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsU2FsdWQsWExWLFJFR04sUkVHTixSRUdOLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKVlJUWCxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsU2FsdWQsWExWLFZSVFgsVlJUWCxWUlRYLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKVE1PLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxTYWx1ZCxYTFYsVE1PLFRNTyxUTU8sRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpESFIsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLFNhbHVkLFhMVixESFIsREhSLERIUixFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCklTUkcsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLFNhbHVkLFhMVixJU1JHLElTUkcsSVNSRyxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCk1EVCxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsU2FsdWQsWExWLE1EVCxNRFQsTURULEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKQlNYLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxTYWx1ZCxYTFYsQlNYLEJTWCxCU1gsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpTWUssQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLFNhbHVkLFhMVixTWUssU1lLLFNZSyxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xClpUUyxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsU2FsdWQsWExWLFpUUyxaVFMsWlRTLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKQk1ZLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxTYWx1ZCxYTFYsQk1ZLEJNWSxCTVksRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpIRCxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsQ29uc3VtbyBEaXNjcmVjaW9uYWwsWExZLEhELEhELEhELEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKTE9XLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxDb25zdW1vIERpc2NyZWNpb25hbCxYTFksTE9XLExPVyxMT1csRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpNQ0QsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLENvbnN1bW8gRGlzY3JlY2lvbmFsLFhMWSxNQ0QsTUNELE1DRCxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xClNCVVgsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLENvbnN1bW8gRGlzY3JlY2lvbmFsLFhMWSxTQlVYLFNCVVgsU0JVWCxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCkJLTkcsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLENvbnN1bW8gRGlzY3JlY2lvbmFsLFhMWSxCS05HLEJLTkcsQktORyxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCkFCTkIsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLENvbnN1bW8gRGlzY3JlY2lvbmFsLFhMWSxBQk5CLEFCTkIsQUJOQixFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xClRKWCxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsQ29uc3VtbyBEaXNjcmVjaW9uYWwsWExZLFRKWCxUSlgsVEpYLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKT1JMWSxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsQ29uc3VtbyBEaXNjcmVjaW9uYWwsWExZLE9STFksT1JMWSxPUkxZLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKQVpPLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxDb25zdW1vIERpc2NyZWNpb25hbCxYTFksQVpPLEFaTyxBWk8sRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpNQVIsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLENvbnN1bW8gRGlzY3JlY2lvbmFsLFhMWSxNQVIsTUFSLE1BUixFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCkNNRyxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsQ29uc3VtbyBEaXNjcmVjaW9uYWwsWExZLENNRyxDTUcsQ01HLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKUkNMLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxDb25zdW1vIERpc2NyZWNpb25hbCxYTFksUkNMLFJDTCxSQ0wsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpLTyxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsQ29uc3VtbyBNYXNpdm8sWExQLEtPLEtPLEtPLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKUEVQLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxDb25zdW1vIE1hc2l2byxYTFAsUEVQLFBFUCxQRVAsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpQTSxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsQ29uc3VtbyBNYXNpdm8sWExQLFBNLFBNLFBNLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKTU8sQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLENvbnN1bW8gTWFzaXZvLFhMUCxNTyxNTyxNTyxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCk1ETFosQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLENvbnN1bW8gTWFzaXZvLFhMUCxNRExaLE1ETFosTURMWixFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCkNMLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxDb25zdW1vIE1hc2l2byxYTFAsQ0wsQ0wsQ0wsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpLTUIsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLENvbnN1bW8gTWFzaXZvLFhMUCxLTUIsS01CLEtNQixFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xClRHVCxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsQ29uc3VtbyBNYXNpdm8sWExQLFRHVCxUR1QsVEdULEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKS1IsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLENvbnN1bW8gTWFzaXZvLFhMUCxLUixLUixLUixFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xClRNVVMsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLENvbXVuaWNhY2lvbixYTEMsVE1VUyxUTVVTLFRNVVMsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpWWixBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsQ29tdW5pY2FjaW9uLFhMQyxWWixWWixWWixFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xClQsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLENvbXVuaWNhY2lvbixYTEMsVCxULFQsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpDTUNTQSxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsQ29tdW5pY2FjaW9uLFhMQyxDTUNTQSxDTUNTQSxDTUNTQSxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCkNIVFIsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLENvbXVuaWNhY2lvbixYTEMsQ0hUUixDSFRSLENIVFIsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpFQSxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsQ29tdW5pY2FjaW9uLFhMQyxFQSxFQSxFQSxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xClRUV08sQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLENvbXVuaWNhY2lvbixYTEMsVFRXTyxUVFdPLFRUV08sRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpIT04sQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLEluZHVzdHJpYWwsWExJLEhPTixIT04sSE9OLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKUlRYLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxJbmR1c3RyaWFsLFhMSSxSVFgsUlRYLFJUWCxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCkxNVCxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsSW5kdXN0cmlhbCxYTEksTE1ULExNVCxMTVQsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpOT0MsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLEluZHVzdHJpYWwsWExJLE5PQyxOT0MsTk9DLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKR0QsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLEluZHVzdHJpYWwsWExJLEdELEdELEdELEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKREUsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLEluZHVzdHJpYWwsWExJLERFLERFLERFLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKRVROLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxJbmR1c3RyaWFsLFhMSSxFVE4sRVROLEVUTixFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xClBILEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxJbmR1c3RyaWFsLFhMSSxQSCxQSCxQSCxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCkVNUixBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsSW5kdXN0cmlhbCxYTEksRU1SLEVNUixFTVIsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpJVFcsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLEluZHVzdHJpYWwsWExJLElUVyxJVFcsSVRXLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKV00sQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLEluZHVzdHJpYWwsWExJLFdNLFdNLFdNLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKVU5QLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxJbmR1c3RyaWFsLFhMSSxVTlAsVU5QLFVOUCxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xClVQUyxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsSW5kdXN0cmlhbCxYTEksVVBTLFVQUyxVUFMsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpGRFgsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLEluZHVzdHJpYWwsWExJLEZEWCxGRFgsRkRYLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKVUJFUixBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsSW5kdXN0cmlhbCxYTEksVUJFUixVQkVSLFVCRVIsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpYT00sQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLEVuZXJnaWEsWExFLFhPTSxYT00sWE9NLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKQ09QLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxFbmVyZ2lhLFhMRSxDT1AsQ09QLENPUCxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCkVPRyxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsRW5lcmdpYSxYTEUsRU9HLEVPRyxFT0csRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpTTEIsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLEVuZXJnaWEsWExFLFNMQixTTEIsU0xCLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKT1hZLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxFbmVyZ2lhLFhMRSxPWFksT1hZLE9YWSxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCk1QQyxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsRW5lcmdpYSxYTEUsTVBDLE1QQyxNUEMsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpWTE8sQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLEVuZXJnaWEsWExFLFZMTyxWTE8sVkxPLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKUFNYLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxFbmVyZ2lhLFhMRSxQU1gsUFNYLFBTWCxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCktNSSxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsRW5lcmdpYSxYTEUsS01JLEtNSSxLTUksRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpXTUIsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLEVuZXJnaWEsWExFLFdNQixXTUIsV01CLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKTElOLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxNYXRlcmlhbGVzLFhMQixMSU4sTElOLExJTixFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCkFQRCxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsTWF0ZXJpYWxlcyxYTEIsQVBELEFQRCxBUEQsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpTSFcsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLE1hdGVyaWFsZXMsWExCLFNIVyxTSFcsU0hXLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKRkNYLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxNYXRlcmlhbGVzLFhMQixGQ1gsRkNYLEZDWCxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCk5FTSxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsTWF0ZXJpYWxlcyxYTEIsTkVNLE5FTSxORU0sRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpOVUUsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLE1hdGVyaWFsZXMsWExCLE5VRSxOVUUsTlVFLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKU1RMRCxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsTWF0ZXJpYWxlcyxYTEIsU1RMRCxTVExELFNUTEQsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpET1csQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLE1hdGVyaWFsZXMsWExCLERPVyxET1csRE9XLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKU0FQLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxUZWNub2xvZ2ljbyxYTEssU0FQLFNBUCxTQVAsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpTSE9QLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxUZWNub2xvZ2ljbyxYTEssU0hPUCxTSE9QLFNIT1AsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpTRSxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsQ29uc3VtbyBEaXNjcmVjaW9uYWwsWExZLFNFLFNFLFNFLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKSkQsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLENvbnN1bW8gRGlzY3JlY2lvbmFsLFhMWSxKRCxKRCxKRCxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCkJJRFUsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLENvbXVuaWNhY2lvbixYTEMsQklEVSxCSURVLEJJRFUsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpOVk8sQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLFNhbHVkLFhMVixOVk8sTlZPLE5WTyxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCkFaTixBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsU2FsdWQsWExWLEFaTixBWk4sQVpOLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKU05ZLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxTYWx1ZCxYTFYsU05ZLFNOWSxTTlksRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpCUCxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsRW5lcmdpYSxYTEUsQlAsQlAsQlAsRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpTSEVMLEFjY2nDs24gVVNBL0FEUixGdW5kYW1lbnRhbCxFbmVyZ2lhLFhMRSxTSEVMLFNIRUwsU0hFTCxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xClJJTyxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsTWF0ZXJpYWxlcyxYTEIsUklPLFJJTyxSSU8sRXh0ZXJpb3IsU0ksVW5pdmVyc28gYW1wbGlhZG8gVjYuMQpCSFAsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLE1hdGVyaWFsZXMsWExCLEJIUCxCSFAsQkhQLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEKVUwsQWNjacOzbiBVU0EvQURSLEZ1bmRhbWVudGFsLENvbnN1bW8gTWFzaXZvLFhMUCxVTCxVTCxVTCxFeHRlcmlvcixTSSxVbml2ZXJzbyBhbXBsaWFkbyBWNi4xCkRFTyxBY2Npw7NuIFVTQS9BRFIsRnVuZGFtZW50YWwsQ29uc3VtbyBNYXNpdm8sWExQLERFTyxERU8sREVPLEV4dGVyaW9yLFNJLFVuaXZlcnNvIGFtcGxpYWRvIFY2LjEK
'@
[IO.File]::WriteAllBytes(
    (Join-Path $REC "config\universe_v8_recovered.csv"),
    [Convert]::FromBase64String(($u64 -replace '\s',''))
)


@'
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UniverseRecord:
    canonical_ticker: str
    asset_class: str
    motor: str
    sector: str
    benchmark: str
    market_symbol: str
    fundamentals_symbol: str
    sec_ticker: str
    country: str
    active: bool
    note: str


def load_universe(path: str | Path) -> list[UniverseRecord]:
    path = Path(path)
    out: list[UniverseRecord] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            ticker = (r.get("canonical_ticker") or "").strip().upper()
            if not ticker:
                continue
            out.append(
                UniverseRecord(
                    canonical_ticker=ticker,
                    asset_class=(r.get("asset_class") or "").strip(),
                    motor=(r.get("motor") or "").strip(),
                    sector=(r.get("sector") or "").strip(),
                    benchmark=(r.get("benchmark") or "").strip(),
                    market_symbol=(r.get("market_symbol") or ticker).strip(),
                    fundamentals_symbol=(r.get("fundamentals_symbol") or ticker).strip(),
                    sec_ticker=(r.get("sec_ticker") or "").strip(),
                    country=(r.get("country") or "").strip(),
                    active=(r.get("active") or "SI").strip().upper() != "NO",
                    note=(r.get("note") or "").strip(),
                )
            )
    return out
'@ | Set-Content -Path (Join-Path $REC "src\alpha_data_recovery\universe_registry.py") -Encoding UTF8

@'
from __future__ import annotations

import math
from statistics import mean
from typing import Any


def _finite(x: Any) -> float | None:
    try:
        y = float(x)
    except (TypeError, ValueError):
        return None
    return y if math.isfinite(y) else None


def _series(rows: list[dict[str, Any]], key: str) -> list[float]:
    return [
        float(v)
        for r in rows
        if (v := _finite(r.get(key))) is not None
    ]


def _ret_n(values: list[float], n: int) -> float | None:
    if len(values) <= n or values[-n - 1] == 0:
        return None
    return values[-1] / values[-n - 1] - 1.0


def _sma(values: list[float], n: int) -> float | None:
    if len(values) < n:
        return None
    return mean(values[-n:])


def _daily_return_map(rows: list[dict[str, Any]]) -> dict[str, float]:
    clean: list[tuple[str, float]] = []
    for r in rows:
        ts = str(r.get("timestamp") or "")
        px = _finite(r.get("adj_close"))
        if not ts or px is None or px <= 0:
            continue
        clean.append((ts[:10], px))

    out: dict[str, float] = {}
    for i in range(1, len(clean)):
        d, px = clean[i]
        prev = clean[i - 1][1]
        if prev > 0:
            out[d] = px / prev - 1.0
    return out


def _beta_corr(
    asset_rows: list[dict[str, Any]],
    benchmark_rows: list[dict[str, Any]] | None,
    n: int = 126,
) -> tuple[float | None, float | None]:
    if not benchmark_rows:
        return None, None

    a = _daily_return_map(asset_rows)
    b = _daily_return_map(benchmark_rows)
    dates = sorted(set(a).intersection(b))
    if len(dates) < 30:
        return None, None
    dates = dates[-n:]

    av = [a[d] for d in dates]
    bv = [b[d] for d in dates]
    ma, mb = mean(av), mean(bv)

    cov = sum((x - ma) * (y - mb) for x, y in zip(av, bv))
    vb = sum((y - mb) ** 2 for y in bv)
    va = sum((x - ma) ** 2 for x in av)

    beta = cov / vb if vb > 0 else None
    corr = cov / math.sqrt(va * vb) if va > 0 and vb > 0 else None
    return beta, corr


def compute_sheet_market_metrics(
    asset_rows: list[dict[str, Any]],
    benchmark_rows: list[dict[str, Any]] | None = None,
) -> dict[str, float | None]:
    adj = _series(asset_rows, "adj_close")
    raw = _series(asset_rows, "close")
    vols = _series(asset_rows, "volume")

    last = raw[-1] if raw else (adj[-1] if adj else None)
    sma20 = _sma(adj, 20)
    sma50 = _sma(adj, 50)
    sma200 = _sma(adj, 200)

    avg_vol20 = mean(vols[-20:]) if len(vols) >= 20 else None
    avg_vol60 = mean(vols[-60:]) if len(vols) >= 60 else None

    b_adj = _series(benchmark_rows or [], "adj_close")
    ret3 = _ret_n(adj, 63)
    ret6 = _ret_n(adj, 126)
    bret3 = _ret_n(b_adj, 63)
    bret6 = _ret_n(b_adj, 126)
    beta, corr = _beta_corr(asset_rows, benchmark_rows, 126)

    high_1y = max(adj[-252:]) if len(adj) >= 2 else None

    return {
        "dist_sma20": (last / sma20 - 1.0) if last is not None and sma20 not in (None, 0) else None,
        "dist_sma50": (last / sma50 - 1.0) if last is not None and sma50 not in (None, 0) else None,
        "dist_sma200": (last / sma200 - 1.0) if last is not None and sma200 not in (None, 0) else None,
        "avg_vol_20d": avg_vol20,
        "dollar_volume_20d_aligned": (
            avg_vol20 * last
            if avg_vol20 is not None and last is not None
            else None
        ),
        "relative_volume_20v60_aligned": (
            avg_vol20 / avg_vol60
            if avg_vol20 is not None and avg_vol60 not in (None, 0)
            else None
        ),
        "rs_3m": (
            ret3 - bret3
            if ret3 is not None and bret3 is not None
            else None
        ),
        "rs_6m": (
            ret6 - bret6
            if ret6 is not None and bret6 is not None
            else None
        ),
        "beta_6m": beta,
        "corr_6m": corr,
        "dist_52w_high": (
            last / high_1y - 1.0
            if last is not None and high_1y not in (None, 0)
            else None
        ),
    }
'@ | Set-Content -Path (Join-Path $REC "src\alpha_data_recovery\market_sheet_metrics.py") -Encoding UTF8

@'
from __future__ import annotations

import http.cookiejar
import json
import math
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPCookieProcessor, Request, build_opener


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/153 Safari/537.36"
)
YQ1 = "https://query1.finance.yahoo.com"
YQ2 = "https://query2.finance.yahoo.com"


def _finite(value: Any) -> float | None:
    if isinstance(value, dict):
        if "raw" in value:
            value = value.get("raw")
        elif "fmt" in value:
            value = value.get("fmt")
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _text(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("raw") or value.get("fmt")
    if value is None:
        return None
    s = str(value).strip()
    return s or None


class YahooSession:
    def __init__(self) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.jar))
        self.crumb: str | None = None

    def _request(self, url: str) -> bytes:
        req = Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "application/json,text/plain,*/*",
            },
        )
        with self.opener.open(req, timeout=20) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}")
            return resp.read()

    def bootstrap(self) -> None:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                try:
                    self._request("https://fc.yahoo.com")
                except Exception:
                    pass
                raw = self._request(f"{YQ1}/v1/test/getcrumb")
                crumb = raw.decode("utf-8").strip()
                if not crumb or "<html" in crumb.lower():
                    raise RuntimeError("invalid Yahoo crumb")
                self.crumb = crumb
                return
            except Exception as exc:
                last_error = exc
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"Yahoo session bootstrap failed: {last_error}")

    def quote_summary(self, symbol: str) -> tuple[dict[str, Any], str]:
        if not self.crumb:
            self.bootstrap()

        modules = ",".join([
            "price",
            "financialData",
            "defaultKeyStatistics",
            "summaryDetail",
            "assetProfile",
            "calendarEvents",
        ])
        encoded = quote(symbol, safe="")
        qs = quote(modules, safe=",")
        crumb = quote(self.crumb or "", safe="")

        last_error: Exception | None = None
        for idx, base in enumerate((YQ2, YQ1)):
            url = (
                f"{base}/v10/finance/quoteSummary/{encoded}"
                f"?modules={qs}&crumb={crumb}"
            )
            for attempt in range(2):
                try:
                    payload = json.loads(self._request(url).decode("utf-8"))
                    err = (payload.get("quoteSummary") or {}).get("error")
                    if err:
                        raise RuntimeError(str(err))
                    result = ((payload.get("quoteSummary") or {}).get("result") or [])
                    if not result:
                        raise RuntimeError("Yahoo quoteSummary returned no result")
                    return result[0], ("none" if idx == 0 else "query1")
                except (
                    HTTPError,
                    URLError,
                    TimeoutError,
                    RuntimeError,
                    json.JSONDecodeError,
                ) as exc:
                    last_error = exc
                    time.sleep(0.4 * (attempt + 1))
        raise RuntimeError(f"Yahoo quoteSummary failed for {symbol}: {last_error}")


def normalize_quote_summary(result: dict[str, Any]) -> dict[str, Any]:
    price = result.get("price") or {}
    fd = result.get("financialData") or {}
    ks = result.get("defaultKeyStatistics") or {}
    sd = result.get("summaryDetail") or {}
    ap = result.get("assetProfile") or {}

    current_price = _finite(price.get("regularMarketPrice"))
    market_cap = _finite(price.get("marketCap")) or _finite(sd.get("marketCap"))
    eps = _finite(ks.get("trailingEps"))
    fwd_eps = _finite(ks.get("forwardEps"))

    pe = _finite(sd.get("trailingPE"))
    if pe is None and current_price is not None and eps not in (None, 0):
        pe = current_price / eps

    fwd_pe = _finite(sd.get("forwardPE"))
    if fwd_pe is None and current_price is not None and fwd_eps not in (None, 0):
        fwd_pe = current_price / fwd_eps

    fcf = _finite(fd.get("freeCashflow"))
    target = _finite(fd.get("targetMeanPrice"))

    return {
        "company_name": _text(price.get("longName")) or _text(price.get("shortName")),
        "sector": _text(ap.get("sector")),
        "industry": _text(ap.get("industry")),
        "currency": _text(price.get("currency")) or _text(sd.get("currency")),
        "price": current_price,
        "market_cap": market_cap,
        "pe": pe,
        "fwd_pe": fwd_pe,
        "peg": _finite(ks.get("pegRatio")),
        "roe": _finite(fd.get("returnOnEquity")),
        "roa": _finite(fd.get("returnOnAssets")),
        "debt_equity": _finite(fd.get("debtToEquity")),
        "net_margin": _finite(fd.get("profitMargins")),
        "eps_growth": _finite(fd.get("earningsGrowth")),
        "revenue_growth": _finite(fd.get("revenueGrowth")),
        "free_cash_flow": fcf,
        "fcf_yield": (
            fcf / market_cap
            if fcf is not None and market_cap not in (None, 0)
            else None
        ),
        "ev_ebitda": _finite(ks.get("enterpriseToEbitda")),
        "current_ratio": _finite(fd.get("currentRatio")),
        "quick_ratio": _finite(fd.get("quickRatio")),
        "dividend_yield": _finite(sd.get("dividendYield")),
        "beta": _finite(ks.get("beta")),
        "target_mean_price": target,
        "target_upside": (
            target / current_price - 1.0
            if target is not None and current_price not in (None, 0)
            else None
        ),
        "recommendation_mean": _finite(fd.get("recommendationMean")),
        "price_book": _finite(ks.get("priceToBook")),
        "shares_outstanding": _finite(ks.get("sharesOutstanding")),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
'@ | Set-Content -Path (Join-Path $REC "src\alpha_data_recovery\yahoo_fundamentals.py") -Encoding UTF8

@'
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .contracts import AuditValue
from .sec_companyfacts import (
    fetch_companyfacts,
    fetch_ticker_map,
    sec_raw_fundamentals,
)
from .yahoo_fundamentals import YahooSession, normalize_quote_summary


YAHOO_SOURCE = "Yahoo Finance quoteSummary"
SEC_SOURCE = "SEC companyfacts"


def _v(x: dict[str, Any] | None) -> float | None:
    return None if not x else float(x["val"])


def _asof(x: dict[str, Any] | None) -> str | None:
    return None if not x else x.get("end") or x.get("filed")


def _safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b in (None, 0):
        return None
    return a / b


def sec_derived(raw: dict[str, Any]) -> dict[str, tuple[float | None, str | None, str]]:
    latest = raw["latest"]
    previous = raw["previous"]

    revenue = _v(latest["revenue"])
    prev_revenue = _v(previous["revenue"])
    net_income = _v(latest["net_income"])
    assets = _v(latest["assets"])
    equity = _v(latest["equity"])
    debt = _v(latest["debt"])
    eps = _v(latest["eps_diluted"])
    prev_eps = _v(previous["eps_diluted"])
    cfo = _v(latest["cash_from_operations"])
    capex = _v(latest["capex"])
    ca = _v(latest["current_assets"])
    cl = _v(latest["current_liabilities"])

    fcf = None
    if cfo is not None:
        fcf = cfo - (abs(capex) if capex is not None else 0.0)

    def best_asof(*items: dict[str, Any] | None) -> str | None:
        vals = [x for x in (_asof(i) for i in items) if x]
        return max(vals) if vals else None

    return {
        "roe": (_safe_div(net_income, equity), best_asof(latest["net_income"], latest["equity"]), "Net income / equity"),
        "roa": (_safe_div(net_income, assets), best_asof(latest["net_income"], latest["assets"]), "Net income / assets"),
        "debt_equity": (
            None if debt is None or equity in (None, 0) else debt / equity * 100.0,
            best_asof(latest["debt"], latest["equity"]),
            "Debt / equity * 100 to match Yahoo convention",
        ),
        "net_margin": (_safe_div(net_income, revenue), best_asof(latest["net_income"], latest["revenue"]), "Net income / revenue"),
        "eps_growth": (
            None if eps is None or prev_eps in (None, 0) else eps / prev_eps - 1.0,
            _asof(latest["eps_diluted"]),
            "Annual diluted EPS growth",
        ),
        "revenue_growth": (
            None if revenue is None or prev_revenue in (None, 0) else revenue / prev_revenue - 1.0,
            _asof(latest["revenue"]),
            "Annual revenue growth",
        ),
        "free_cash_flow": (
            fcf,
            best_asof(latest["cash_from_operations"], latest["capex"]),
            "CFO - abs(CapEx)",
        ),
        "current_ratio": (
            _safe_div(ca, cl),
            best_asof(latest["current_assets"], latest["current_liabilities"]),
            "Current assets / current liabilities",
        ),
        "eps_diluted_sec": (eps, _asof(latest["eps_diluted"]), "Latest annual diluted EPS"),
        "equity_sec": (equity, _asof(latest["equity"]), "Latest annual equity"),
    }


@dataclass
class FundamentalSnapshot:
    ticker: str
    yahoo_symbol: str
    sec_ticker: str
    retrieved_at: str
    fields: dict[str, AuditValue]
    overall_status: str
    coverage: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "yahoo_symbol": self.yahoo_symbol,
            "sec_ticker": self.sec_ticker,
            "retrieved_at": self.retrieved_at,
            "overall_status": self.overall_status,
            "coverage": self.coverage,
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
        }


def recover_fundamentals(
    ticker: str,
    yahoo_symbol: str | None = None,
    sec_ticker: str | None = None,
    yahoo_session: YahooSession | None = None,
    sec_map: dict[str, str] | None = None,
) -> FundamentalSnapshot:
    ticker = ticker.upper()
    yahoo_symbol = (yahoo_symbol or ticker).upper()
    sec_ticker = (sec_ticker or "").upper()
    retrieved = datetime.now(timezone.utc).isoformat()

    fields: dict[str, AuditValue] = {}
    yahoo_error: str | None = None
    sec_error: str | None = None
    yahoo_data: dict[str, Any] = {}
    sec_data: dict[str, tuple[float | None, str | None, str]] = {}
    sec_entity_name: str | None = None

    session = yahoo_session or YahooSession()
    try:
        result, yf_fallback = session.quote_summary(yahoo_symbol)
        yahoo_data = normalize_quote_summary(result)
        y_asof = yahoo_data["retrieved_at"]
        for name, value in yahoo_data.items():
            if name == "retrieved_at":
                continue
            fields[name] = AuditValue(
                value=value,
                source=YAHOO_SOURCE,
                asof=y_asof,
                status="OK" if value is not None else "MISSING",
                fallback=yf_fallback,
                detail="Provider snapshot; filing-period semantics may differ by field.",
            )
    except Exception as exc:
        yahoo_error = str(exc)

    critical = [
        "roe", "roa", "debt_equity",
        "net_margin", "eps_growth", "revenue_growth",
    ]
    critical_ok = sum(
        1 for name in critical
        if fields.get(name) is not None and fields[name].value is not None
    )
    need_sec = yahoo_error is not None or critical_ok < 5 or (
        fields.get("free_cash_flow") is None
        or fields["free_cash_flow"].value is None
    )

    if need_sec and sec_ticker:
        try:
            smap = sec_map if sec_map is not None else fetch_ticker_map()
            cik = smap.get(sec_ticker)
            if not cik:
                raise RuntimeError(f"SEC CIK not found for {sec_ticker}")
            companyfacts = fetch_companyfacts(cik)
            raw = sec_raw_fundamentals(companyfacts)
            sec_entity_name = raw.get("entity_name")
            sec_data = sec_derived(raw)
        except Exception as exc:
            sec_error = str(exc)
    elif need_sec and not sec_ticker:
        sec_error = "No SEC ticker configured"

    fallback_fields = {
        "roe", "roa", "debt_equity", "net_margin",
        "eps_growth", "revenue_growth", "free_cash_flow",
        "current_ratio",
    }
    for name in fallback_fields:
        current = fields.get(name)
        sec_value, sec_asof, detail = sec_data.get(name, (None, None, ""))
        if current is None or current.value is None:
            fields[name] = AuditValue(
                value=sec_value,
                source=SEC_SOURCE,
                asof=sec_asof,
                status="FALLBACK" if sec_value is not None else "MISSING",
                fallback="SEC companyfacts" if sec_value is not None else "none",
                detail=detail or "SEC fallback unavailable.",
            )

    eps_sec, eps_asof, _ = sec_data.get("eps_diluted_sec", (None, None, ""))
    equity_sec, eq_asof, _ = sec_data.get("equity_sec", (None, None, ""))
    price = fields.get("price").value if fields.get("price") else None
    market_cap = fields.get("market_cap").value if fields.get("market_cap") else None

    if (fields.get("pe") is None or fields["pe"].value is None) and price is not None and eps_sec not in (None, 0):
        fields["pe"] = AuditValue(
            price / eps_sec,
            "derived: Yahoo price + SEC EPS",
            max(x for x in [fields["price"].asof, eps_asof] if x),
            "FALLBACK",
            "SEC companyfacts",
            "Price / latest annual diluted EPS",
        )

    if (fields.get("price_book") is None or fields["price_book"].value is None) and market_cap is not None and equity_sec not in (None, 0):
        fields["price_book"] = AuditValue(
            market_cap / equity_sec,
            "derived: Yahoo market cap + SEC equity",
            max(x for x in [fields["market_cap"].asof, eq_asof] if x),
            "FALLBACK",
            "SEC companyfacts",
            "Market cap / latest annual equity",
        )

    fcf = fields.get("free_cash_flow").value if fields.get("free_cash_flow") else None
    if (fields.get("fcf_yield") is None or fields["fcf_yield"].value is None) and fcf is not None and market_cap not in (None, 0):
        fields["fcf_yield"] = AuditValue(
            fcf / market_cap,
            "derived: FCF / market cap",
            fields.get("free_cash_flow").asof,
            "FALLBACK",
            fields.get("free_cash_flow").fallback,
            "Free cash flow / market capitalization",
        )

    if (fields.get("company_name") is None or not fields["company_name"].value) and sec_entity_name:
        fields["company_name"] = AuditValue(
            sec_entity_name,
            SEC_SOURCE,
            None,
            "FALLBACK",
            "SEC companyfacts",
            "SEC entity name",
        )

    required = [
        "company_name", "market_cap", "pe", "roe",
        "debt_equity", "net_margin", "revenue_growth",
        "free_cash_flow",
    ]
    available = sum(
        1 for name in required
        if fields.get(name) is not None and fields[name].value is not None
    )
    coverage = available / len(required)

    if coverage >= 0.875 and yahoo_error is None:
        overall = "OK"
    elif coverage >= 0.625:
        overall = "PARTIAL"
    else:
        overall = "INCOMPLETE"

    fields["_yahoo_error"] = AuditValue(
        yahoo_error, YAHOO_SOURCE, retrieved,
        "OK" if yahoo_error is None else "ERROR", "none", ""
    )
    fields["_sec_error"] = AuditValue(
        sec_error, SEC_SOURCE, retrieved,
        "OK" if sec_error is None else "ERROR", "none", ""
    )

    return FundamentalSnapshot(
        ticker=ticker,
        yahoo_symbol=yahoo_symbol,
        sec_ticker=sec_ticker,
        retrieved_at=retrieved,
        fields=fields,
        overall_status=overall,
        coverage=coverage,
    )
'@ | Set-Content -Path (Join-Path $REC "src\alpha_data_recovery\fundamentals.py") -Encoding UTF8

@'
from __future__ import annotations

from typing import Any

from .market_sheet_metrics import compute_sheet_market_metrics


FUND_HEADERS = [
    "Ticker","Nombre","Sector","Precio USD","Market Cap","P/E","Fwd P/E","PEG",
    "ROE","ROA","Debt/Eq","Margen Neto","EPS Growth","Revenue Growth","FCF",
    "FCF Yield","EV/EBITDA","Current Ratio","Quick Ratio","Dividend Yield",
    "Beta Yahoo","Target Price","Upside","Recom. Analistas",
    "Score Calidad (Shrink)","Score Crecimiento (Shrink)","Score Valuación (Shrink)",
    "Fuente","Price / Book",
]

MKT_HEADERS = [
    "Ticker","Yahoo Symbol","Benchmark","Precio","Var 1D","Ret 1M","Ret 3M",
    "Ret 6M","Ret 12M","SMA20","SMA50","SMA200","Dist SMA20","Dist SMA50",
    "Dist SMA200","RSI14","Vol 20D","Vol 60D","Vol 1A","Downside Dev 60D",
    "Max Drawdown 1A","Avg Vol 20D","Dollar Vol 20D","Vol 20/60","RS 3M",
    "RS 6M","Beta 6M","Corr 6M","Dist 52W High","Score Tendencia","Score RS",
    "Score Participación","Score Mercado","Score Volatilidad","Score Tail Risk",
    "Score Liquidez","Beta/Corr Info Score","RISK SCORE","Cobertura Mercado",
    "Fuente","Actualización",
]

FUND_SCORE_COLUMNS = {
    "Score Calidad (Shrink)",
    "Score Crecimiento (Shrink)",
    "Score Valuación (Shrink)",
}

MKT_SCORE_COLUMNS = {
    "Score Tendencia","Score RS","Score Participación","Score Mercado",
    "Score Volatilidad","Score Tail Risk","Score Liquidez",
    "Beta/Corr Info Score","RISK SCORE",
}


def _field(record: dict[str, Any], name: str) -> Any:
    return ((record.get("fields") or {}).get(name) or {}).get("value")


def _sources(record: dict[str, Any]) -> str:
    names = [
        "pe","roe","debt_equity","net_margin","revenue_growth","free_cash_flow"
    ]
    sources = {
        ((record.get("fields") or {}).get(n) or {}).get("source")
        for n in names
        if ((record.get("fields") or {}).get(n) or {}).get("value") is not None
    }
    sources.discard(None)
    if any("SEC" in str(s) for s in sources) and any("Yahoo" in str(s) for s in sources):
        return "Yahoo + SEC"
    if sources:
        return " | ".join(sorted(str(s) for s in sources))
    return ""


def fundamental_payload_row(
    universe,
    record: dict[str, Any],
) -> dict[str, Any]:
    currency = _field(record, "currency")
    provider_price = _field(record, "price")
    price_usd = provider_price if str(currency or "").upper() == "USD" else None

    return dict(zip(FUND_HEADERS, [
        universe.canonical_ticker,
        _field(record, "company_name"),
        universe.sector,
        price_usd,
        _field(record, "market_cap"),
        _field(record, "pe"),
        _field(record, "fwd_pe"),
        _field(record, "peg"),
        _field(record, "roe"),
        _field(record, "roa"),
        _field(record, "debt_equity"),
        _field(record, "net_margin"),
        _field(record, "eps_growth"),
        _field(record, "revenue_growth"),
        _field(record, "free_cash_flow"),
        _field(record, "fcf_yield"),
        _field(record, "ev_ebitda"),
        _field(record, "current_ratio"),
        _field(record, "quick_ratio"),
        _field(record, "dividend_yield"),
        _field(record, "beta"),
        _field(record, "target_mean_price"),
        _field(record, "target_upside"),
        _field(record, "recommendation_mean"),
        None,
        None,
        None,
        _sources(record),
        _field(record, "price_book"),
    ]))


def market_payload_row(
    universe,
    snapshot: dict[str, Any] | None,
    asset_rows: list[dict[str, Any]] | None,
    benchmark_rows: list[dict[str, Any]] | None,
    error: str | None = None,
) -> dict[str, Any]:
    if not snapshot or not asset_rows:
        row = {h: None for h in MKT_HEADERS}
        row["Ticker"] = universe.canonical_ticker
        row["Yahoo Symbol"] = universe.market_symbol
        row["Benchmark"] = universe.benchmark
        row["Cobertura Mercado"] = 0.0
        row["Fuente"] = f"ERROR: {error}" if error else "MISSING"
        return row

    f = snapshot["fields"]
    m = snapshot["metrics"]
    extra = compute_sheet_market_metrics(asset_rows, benchmark_rows)

    def fv(name):
        return (f.get(name) or {}).get("value")

    def mv(name):
        return (m.get(name) or {}).get("value")

    return dict(zip(MKT_HEADERS, [
        universe.canonical_ticker,
        universe.market_symbol,
        universe.benchmark,
        fv("price"),
        fv("var_1d"),
        mv("ret_1m"),
        mv("ret_3m"),
        mv("ret_6m"),
        mv("ret_12m"),
        mv("sma_20"),
        mv("sma_50"),
        mv("sma_200"),
        extra["dist_sma20"],
        extra["dist_sma50"],
        extra["dist_sma200"],
        mv("rsi_14"),
        mv("vol_20d"),
        mv("vol_60d"),
        mv("vol_1y"),
        mv("downside_vol_60d"),
        mv("max_drawdown_1y"),
        extra["avg_vol_20d"],
        extra["dollar_volume_20d_aligned"],
        extra["relative_volume_20v60_aligned"],
        extra["rs_3m"],
        extra["rs_6m"],
        extra["beta_6m"],
        extra["corr_6m"],
        extra["dist_52w_high"],
        None,None,None,None,None,None,None,None,None,
        snapshot.get("coverage"),
        (f.get("price") or {}).get("source"),
        (f.get("price") or {}).get("asof"),
    ]))
'@ | Set-Content -Path (Join-Path $REC "src\alpha_data_recovery\sheet_payloads.py") -Encoding UTF8

@'
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alpha_data_recovery.fundamentals import recover_fundamentals
from alpha_data_recovery.market_sheet_metrics import compute_sheet_market_metrics
from alpha_data_recovery.sec_companyfacts import fetch_ticker_map
from alpha_data_recovery.sheet_payloads import (
    FUND_HEADERS, MKT_HEADERS,
    FUND_SCORE_COLUMNS, MKT_SCORE_COLUMNS,
    fundamental_payload_row, market_payload_row,
)
from alpha_data_recovery.universe_registry import load_universe
from alpha_data_recovery.yahoo_chart import recover_market
from alpha_data_recovery.yahoo_fundamentals import YahooSession


def write_csv(path: Path, headers: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=headers, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def market_worker(symbol: str):
    snap, rows = recover_market(symbol, symbol)
    return snap.to_dict(), rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market-workers", type=int, default=6)
    args = parser.parse_args()

    universe_path = ROOT / "config" / "universe_v8_recovered.csv"
    universe = [u for u in load_universe(universe_path) if u.active]
    fundamentals_u = [u for u in universe if u.motor == "Fundamental"]
    market_u = [u for u in universe if u.motor != "Renta Fija"]
    rf_u = [u for u in universe if u.motor == "Renta Fija"]

    print(
        f"UNIVERSE total={len(universe)} "
        f"fundamental={len(fundamentals_u)} "
        f"market={len(market_u)} rf={len(rf_u)}"
    )

    if len(universe) != 228:
        raise RuntimeError(f"Universe structural mismatch: {len(universe)} != 228")
    if len(fundamentals_u) != 187:
        raise RuntimeError(f"Fundamental universe mismatch: {len(fundamentals_u)} != 187")
    if len(market_u) != 200:
        raise RuntimeError(f"Market universe mismatch: {len(market_u)} != 200")
    if len(rf_u) != 28:
        raise RuntimeError(f"RF universe mismatch: {len(rf_u)} != 28")

    staging = ROOT / "outputs" / "data_recovery_v1" / "staging"
    staging.mkdir(parents=True, exist_ok=True)

    symbols = sorted({
        s
        for u in market_u
        for s in (u.market_symbol, u.benchmark)
        if s
    })

    print(f"[MARKET] unique provider symbols={len(symbols)}")
    market_results: dict[str, tuple[dict, list[dict]]] = {}
    market_errors: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=max(1, min(args.market_workers, 8))) as ex:
        futs = {ex.submit(market_worker, s): s for s in symbols}
        done = 0
        for fut in as_completed(futs):
            symbol = futs[fut]
            try:
                market_results[symbol] = fut.result()
            except Exception as exc:
                market_errors[symbol] = str(exc)
            done += 1
            if done % 25 == 0 or done == len(symbols):
                print(
                    f"  market {done}/{len(symbols)} "
                    f"ok={len(market_results)} errors={len(market_errors)}"
                )

    yf = YahooSession()
    yahoo_bootstrap_error = None
    try:
        yf.bootstrap()
        print("[FUND] Yahoo session OK")
    except Exception as exc:
        yahoo_bootstrap_error = str(exc)
        print(f"[FUND] Yahoo session WARN: {exc}")

    try:
        sec_map = fetch_ticker_map()
        print(f"[FUND] SEC map OK tickers={len(sec_map)}")
    except Exception as exc:
        sec_map = {}
        print(f"[FUND] SEC map WARN: {exc}")

    fund_records: dict[str, dict] = {}
    for i, u in enumerate(fundamentals_u, start=1):
        try:
            snap = recover_fundamentals(
                ticker=u.canonical_ticker,
                yahoo_symbol=u.fundamentals_symbol,
                sec_ticker=u.sec_ticker,
                yahoo_session=yf,
                sec_map=sec_map,
            )
            fund_records[u.canonical_ticker] = snap.to_dict()
        except Exception as exc:
            fund_records[u.canonical_ticker] = {
                "ticker": u.canonical_ticker,
                "yahoo_symbol": u.fundamentals_symbol,
                "sec_ticker": u.sec_ticker,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "overall_status": "INCOMPLETE",
                "coverage": 0.0,
                "fields": {
                    "_orchestrator_error": {
                        "value": str(exc),
                        "source": "DR1-C orchestrator",
                        "asof": datetime.now(timezone.utc).isoformat(),
                        "status": "ERROR",
                        "fallback": "none",
                        "detail": "",
                    }
                },
            }
        if i % 25 == 0 or i == len(fundamentals_u):
            c = Counter(r["overall_status"] for r in fund_records.values())
            print(f"  fundamentals {i}/{len(fundamentals_u)} status={dict(c)}")
        time.sleep(0.08)

    fund_payload = [
        fundamental_payload_row(u, fund_records[u.canonical_ticker])
        for u in fundamentals_u
    ]

    market_payload = []
    audit_rows = []
    failures = []

    for u in market_u:
        asset = market_results.get(u.market_symbol)
        bench = market_results.get(u.benchmark) if u.benchmark else None

        if asset:
            snap, rows = asset
            b_rows = bench[1] if bench else None
            market_payload.append(
                market_payload_row(u, snap, rows, b_rows)
            )

            for field, a in (snap.get("fields") or {}).items():
                audit_rows.append({
                    "ticker": u.canonical_ticker,
                    "module": "market",
                    "provider_symbol": u.market_symbol,
                    "field": field,
                    "value": a.get("value"),
                    "source": a.get("source"),
                    "asof": a.get("asof"),
                    "status": a.get("status"),
                    "fallback": a.get("fallback"),
                    "detail": a.get("detail"),
                })

            for field, a in (snap.get("metrics") or {}).items():
                audit_rows.append({
                    "ticker": u.canonical_ticker,
                    "module": "market",
                    "provider_symbol": u.market_symbol,
                    "field": field,
                    "value": a.get("value"),
                    "source": a.get("source"),
                    "asof": a.get("asof"),
                    "status": a.get("status"),
                    "fallback": a.get("fallback"),
                    "detail": a.get("detail"),
                })

            extra = compute_sheet_market_metrics(rows, b_rows)
            for field, value in extra.items():
                audit_rows.append({
                    "ticker": u.canonical_ticker,
                    "module": "market",
                    "provider_symbol": u.market_symbol,
                    "field": field,
                    "value": value,
                    "source": "derived: Yahoo OHLCV aligned",
                    "asof": (snap.get("fields", {}).get("latest_daily_close", {}) or {}).get("asof"),
                    "status": "OK" if value is not None else "MISSING",
                    "fallback": "none",
                    "detail": "DR1-C raw market metric; no V8 score.",
                })
        else:
            err = market_errors.get(u.market_symbol, "market symbol not recovered")
            market_payload.append(
                market_payload_row(u, None, None, None, err)
            )
            failures.append({
                "ticker": u.canonical_ticker,
                "module": "market",
                "provider_symbol": u.market_symbol,
                "error": err,
            })

    for u in fundamentals_u:
        rec = fund_records[u.canonical_ticker]
        for field, a in (rec.get("fields") or {}).items():
            audit_rows.append({
                "ticker": u.canonical_ticker,
                "module": "fundamentals",
                "provider_symbol": u.fundamentals_symbol,
                "field": field,
                "value": a.get("value"),
                "source": a.get("source"),
                "asof": a.get("asof"),
                "status": a.get("status"),
                "fallback": a.get("fallback"),
                "detail": a.get("detail"),
            })

        if rec["overall_status"] == "INCOMPLETE":
            failures.append({
                "ticker": u.canonical_ticker,
                "module": "fundamentals",
                "provider_symbol": u.fundamentals_symbol,
                "error": (
                    ((rec.get("fields") or {}).get("_yahoo_error") or {}).get("value")
                    or ((rec.get("fields") or {}).get("_orchestrator_error") or {}).get("value")
                    or "incomplete coverage"
                ),
            })

    fund_path = staging / "fundamentales_payload_latest.csv"
    mkt_path = staging / "mercado_riesgo_payload_latest.csv"
    audit_path = staging / "data_audit_long_latest.csv"
    fail_path = staging / "provider_failures_latest.csv"
    uni_path = staging / "universe_registry_latest.csv"

    write_csv(fund_path, FUND_HEADERS, fund_payload)
    write_csv(mkt_path, MKT_HEADERS, market_payload)
    write_csv(
        audit_path,
        ["ticker","module","provider_symbol","field","value","source","asof","status","fallback","detail"],
        audit_rows,
    )
    write_csv(
        fail_path,
        ["ticker","module","provider_symbol","error"],
        failures,
    )

    with universe_path.open("r", encoding="utf-8-sig") as src:
        uni_path.write_text(src.read(), encoding="utf-8-sig")

    fund_status = Counter(r["overall_status"] for r in fund_records.values())
    market_ok = sum(
        1 for u in market_u if u.market_symbol in market_results
    )

    summary = {
        "stage": "ALPHA_ENGINE_DATA_RECOVERY_V1_DR1C",
        "asof": datetime.now(timezone.utc).isoformat(),
        "universe": {
            "total": len(universe),
            "fundamental": len(fundamentals_u),
            "market_non_rf": len(market_u),
            "renta_fija": len(rf_u),
        },
        "market": {
            "asset_rows": len(market_payload),
            "asset_symbols_recovered": market_ok,
            "asset_symbols_missing": len(market_u) - market_ok,
            "unique_provider_symbols_requested": len(symbols),
            "provider_symbols_failed": len(market_errors),
        },
        "fundamentals": {
            "rows": len(fund_payload),
            "status_counts": dict(fund_status),
            "yahoo_bootstrap_error": yahoo_bootstrap_error,
        },
        "audit_rows": len(audit_rows),
        "provider_failures": len(failures),
        "score_columns_policy": {
            "fundamental_scores_blank": True,
            "market_scores_blank": True,
            "v8_v10_scores_imported": False,
        },
        "mutation_policy": {
            "v13_model": False,
            "v13_policy": False,
            "v13_outputs": False,
            "sheets": False,
            "web": False,
            "product_state": False,
        },
    }

    summary_path = staging / "recovery_coverage_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("")
    print("DR1-C STAGING WRITTEN")
    print(f"  {fund_path}")
    print(f"  {mkt_path}")
    print(f"  {audit_path}")
    print(f"  {fail_path}")
    print(f"  {summary_path}")
    print("")
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    # Provider gaps are NOT structural failures. They are audited.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'@ | Set-Content -Path (Join-Path $REC "scripts\run_dr1c_staging.py") -Encoding UTF8

@'
from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from alpha_data_recovery.market_sheet_metrics import compute_sheet_market_metrics
from alpha_data_recovery.sheet_payloads import (
    FUND_HEADERS, MKT_HEADERS,
    FUND_SCORE_COLUMNS, MKT_SCORE_COLUMNS,
)
from alpha_data_recovery.universe_registry import load_universe


class TestDR1C(unittest.TestCase):
    def test_exact_legacy_payload_widths(self):
        self.assertEqual(len(FUND_HEADERS), 29)
        self.assertEqual(len(MKT_HEADERS), 41)

    def test_score_columns_are_explicitly_identified(self):
        self.assertEqual(len(FUND_SCORE_COLUMNS), 3)
        self.assertEqual(len(MKT_SCORE_COLUMNS), 9)
        self.assertIn("RISK SCORE", MKT_SCORE_COLUMNS)

    def test_market_extra_metrics(self):
        rows = []
        for i in range(300):
            rows.append({
                "timestamp": f"2026-01-{(i % 28) + 1:02d}T20:00:00+00:00-{i}",
                "adj_close": 100.0 + i,
                "close": 100.0 + i,
                "volume": 1000.0 + i,
            })
        m = compute_sheet_market_metrics(rows, rows)
        self.assertIsNotNone(m["dist_sma20"])
        self.assertIsNotNone(m["avg_vol_20d"])
        self.assertAlmostEqual(m["rs_3m"], 0.0)
        self.assertAlmostEqual(m["beta_6m"], 1.0)
        self.assertAlmostEqual(m["corr_6m"], 1.0)

    def test_universe_loader(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "u.csv"
            p.write_text(
                "canonical_ticker,asset_class,motor,sector,benchmark,market_symbol,"
                "fundamentals_symbol,sec_ticker,country,active,note\n"
                "PAMP,Acción,Fundamental,Energia,^MERV,PAMP.BA,PAM,PAM,Argentina,SI,test\n",
                encoding="utf-8",
            )
            u = load_universe(p)[0]
            self.assertEqual(u.canonical_ticker, "PAMP")
            self.assertEqual(u.market_symbol, "PAMP.BA")
            self.assertEqual(u.fundamentals_symbol, "PAM")
            self.assertEqual(u.sec_ticker, "PAM")


if __name__ == "__main__":
    unittest.main()
'@ | Set-Content -Path (Join-Path $REC "tests\test_dr1c_staging.py") -Encoding UTF8

Write-Host ""
Write-Host "[1/5] Unit tests"
Set-Location $REC
python -m unittest discover -s tests -p "test_*.py" -v
if ($LASTEXITCODE -ne 0) { throw "Tests DR1-C fallaron." }

Write-Host ""
Write-Host "[2/5] Full recovered-universe staging"
python scripts\run_dr1c_staging.py
if ($LASTEXITCODE -ne 0) { throw "DR1-C structural staging failed." }

Write-Host ""
Write-Host "[3/5] Payload structural gate"
$STG = Join-Path $REC "outputs\data_recovery_v1\staging"
$fund = Import-Csv (Join-Path $STG "fundamentales_payload_latest.csv")
$mkt  = Import-Csv (Join-Path $STG "mercado_riesgo_payload_latest.csv")

if ($fund.Count -ne 187) { throw "FUND ROW GATE: $($fund.Count) != 187" }
if ($mkt.Count -ne 200) { throw "MKT ROW GATE: $($mkt.Count) != 200" }

if ($fund[0].PSObject.Properties.Count -ne 29) {
    throw "FUND WIDTH GATE: $($fund[0].PSObject.Properties.Count) != 29"
}
if ($mkt[0].PSObject.Properties.Count -ne 41) {
    throw "MKT WIDTH GATE: $($mkt[0].PSObject.Properties.Count) != 41"
}

Write-Host "  [OK] Fundamentales rows=187 cols=29"
Write-Host "  [OK] Mercado & Riesgo rows=200 cols=41"

Write-Host ""
Write-Host "[4/5] Forbidden-score blank gate"
$badFund = $fund | Where-Object {
    $_.'Score Calidad (Shrink)' -or
    $_.'Score Crecimiento (Shrink)' -or
    $_.'Score Valuación (Shrink)'
}
if ($badFund) { throw "FORBIDDEN SCORE GATE: DR1-C populated old fundamental scores." }

$badMkt = $mkt | Where-Object {
    $_.'Score Tendencia' -or
    $_.'Score RS' -or
    $_.'Score Participación' -or
    $_.'Score Mercado' -or
    $_.'Score Volatilidad' -or
    $_.'Score Tail Risk' -or
    $_.'Score Liquidez' -or
    $_.'Beta/Corr Info Score' -or
    $_.'RISK SCORE'
}
if ($badMkt) { throw "FORBIDDEN SCORE GATE: DR1-C populated old market/risk scores." }

Write-Host "  [OK] All V8/V10 score columns are blank"

Write-Host ""
Write-Host "[5/5] V13 immutability"
Set-Location $ROOT
$after = git status --porcelain -- "ALPHA_ENGINE_V13_RETURN_FIRST_MULTI_HORIZON"
if (($before | Out-String) -ne ($after | Out-String)) {
    throw "GUARDRAIL: cambió V13 durante DR1-C."
}

Write-Host ""
Write-Host "============================================================"
Write-Host "DR1-C COMPLETE"
Write-Host "V8 UNIVERSE: RECOVERED"
Write-Host "FUNDAMENTALES PAYLOAD: 187 ROWS / 29 COLS"
Write-Host "MERCADO & RIESGO PAYLOAD: 200 ROWS / 41 COLS"
Write-Host "OLD SCORE COLUMNS: BLANK"
Write-Host "PER-DATUM AUDIT: ACTIVE"
Write-Host "PROVIDER GAPS: RECORDED, NOT SILENTLY IMPUTED"
Write-Host "V13: UNCHANGED"
Write-Host "SHEETS: UNCHANGED"
Write-Host "WEB: UNCHANGED"
Write-Host "PRODUCT STATE: NOT REGENERATED"
Write-Host "============================================================"
Write-Host ""
Write-Host "Pegame desde 'UNIVERSE total=' hasta el final, especialmente el JSON de coverage."
