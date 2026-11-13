param([Parameter(Mandatory=$true)][string]$TaskName)
$ErrorActionPreference = 'Stop'
try {
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    $task = $service.GetFolder('\').GetTask($TaskName)
    $running = @($service.GetRunningTasks(0) | Where-Object { $_.Path -eq ('\' + $TaskName) })
    $events = @()
    try {
        $items = Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-TaskScheduler/Operational';Id=129} -MaxEvents 64 -ErrorAction Stop
        foreach ($item in $items) {
            [xml]$eventXml = $item.ToXml()
            $data = @{}
            foreach ($field in $eventXml.Event.EventData.Data) { $data[$field.Name] = $field.'#text' }
            if ($data.TaskName -eq ('\' + $TaskName)) {
                $events += @{pid=[int]$data.ProcessID;at=$item.TimeCreated.ToUniversalTime().ToString('o')}
            }
        }
    } catch { }
    @{state=[int]$task.State;last_result=[int]$task.LastTaskResult;
      engine_pids=@($running | ForEach-Object {[int]$_.EnginePID});
      launch_events=$events} | ConvertTo-Json -Depth 4 -Compress
} catch { '{}' }
