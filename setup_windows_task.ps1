$TaskName = "AIJobHunterDaily"
$WorkingDirectory = "C:\Tools\AI-Job-Hunter"
$PythonExe = "C:\Users\vkra3\AppData\Local\Programs\Python\Python313\python.exe"
$Arguments = "app.py"

try {
    tzutil /s "India Standard Time" | Out-Null
}
catch {
    Write-Warning "Could not change the system time zone automatically. If needed, set Windows time zone to 'India Standard Time'."
}

$Action = New-ScheduledTaskAction -Execute $PythonExe -WorkingDirectory $WorkingDirectory -Argument $Arguments
$Trigger = New-ScheduledTaskTrigger -Daily -At 10:00
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force

Write-Host "Scheduled task '$TaskName' created for 10:00 AM IST daily."
