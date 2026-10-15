param([ValidateSet('dir', 'file', 'save')][string]$Mode = 'dir')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.Opacity = 0
$owner.Show()
$dialog = $null
try {
    switch ($Mode) {
        'dir' {
            $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
            $dialog.Description = 'NegativeMaster - Select a film folder'
            $dialog.ShowNewFolderButton = $true
        }
        'file' {
            $dialog = New-Object System.Windows.Forms.OpenFileDialog
            $dialog.Title = 'NegativeMaster - Open an image'
            $dialog.Filter = 'Images|*.arw;*.arq;*.cr2;*.cr3;*.nef;*.raf;*.dng;*.rw2;*.orf;*.pef;*.srw;*.3fr;*.iiq;*.raw;*.tif;*.tiff;*.png;*.jpg;*.jpeg;*.bmp;*.webp|All files|*.*'
            $dialog.CheckFileExists = $true
        }
        'save' {
            $dialog = New-Object System.Windows.Forms.SaveFileDialog
            $dialog.Title = 'NegativeMaster - Export image (use the format selected in the app)'
            $dialog.Filter = 'TIFF / JPEG|*.tif;*.tiff;*.jpg;*.jpeg|All files|*.*'
            $dialog.AddExtension = $false
            $dialog.OverwritePrompt = $true
        }
    }
    $path = $null
    if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) {
        if ($Mode -eq 'dir') { $path = $dialog.SelectedPath } else { $path = $dialog.FileName }
    }
    @{ path = $path } | ConvertTo-Json -Compress
} finally {
    if ($null -ne $dialog) { $dialog.Dispose() }
    $owner.Dispose()
}
