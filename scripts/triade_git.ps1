param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$GitArgs
)
$git = Join-Path $PSScriptRoot '..\..\..\tools\mingit\cmd\git.exe'
if (-not (Test-Path -LiteralPath $git)) { throw "Git portable no encontrado: $git" }
$blocked = @('push','fetch','pull','clone','remote')
if ($GitArgs.Count -gt 0 -and $blocked -contains $GitArgs[0]) {
    throw "Operacion remota bloqueada en modo Triade local: $($GitArgs[0])"
}
& $git @GitArgs
exit $LASTEXITCODE
