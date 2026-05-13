param(
    [ValidateSet("detect", "approve", "approve-always", "cancel")]
    [string]$Mode = "detect",
    [string]$Signature = ""
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class MouseNative {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
}
"@

$YES = [string][char]0x662F
$NO = [string][char]0x5426
$AND = [string][char]0x4E14
$SUBMIT = -join @([char]0x63D0, [char]0x4EA4)
$SKIP = -join @([char]0x8DF3, [char]0x8FC7)
$IDEOGRAPHIC_DOT = [string][char]0x3002

function Get-CodexWindows {
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    return $root.FindAll(
        [System.Windows.Automation.TreeScope]::Children,
        [System.Windows.Automation.Condition]::TrueCondition
    ) | Where-Object { $_.Current.Name -eq "Codex" }
}

function Get-VisibleElements($window) {
    $all = $window.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.Condition]::TrueCondition
    )
    $items = @()
    foreach ($element in $all) {
        $name = $element.Current.Name
        if ([string]::IsNullOrWhiteSpace($name) -or $element.Current.IsOffscreen) {
            continue
        }
        $items += [PSCustomObject]@{
            Element = $element
            Name = ($name -replace "\s+", " ").Trim()
            Type = $element.Current.ControlType.ProgrammaticName
            Rect = $element.Current.BoundingRectangle
        }
    }
    return $items
}

function New-VisibleElementItem($element) {
    $name = $element.Current.Name
    if ([string]::IsNullOrWhiteSpace($name) -or $element.Current.IsOffscreen) {
        return $null
    }
    return [PSCustomObject]@{
        Element = $element
        Name = ($name -replace "\s+", " ").Trim()
        Type = $element.Current.ControlType.ProgrammaticName
        Rect = $element.Current.BoundingRectangle
    }
}

function Is-YesName([string]$Name) {
    return $Name -eq $YES -or
        ($Name -like ($YES + "*") -and $Name -notlike ("*" + $AND + "*")) -or
        $Name -match ("^1[\." + [regex]::Escape($IDEOGRAPHIC_DOT) + "]?\s*" + [regex]::Escape($YES))
}

function Is-NoName([string]$Name) {
    return $Name -eq $NO -or
        $Name -like ($NO + "*") -or
        $Name -match ("^3[\." + [regex]::Escape($IDEOGRAPHIC_DOT) + "]?\s*" + [regex]::Escape($NO))
}

function Is-RememberName([string]$Name) {
    if ($Name -like ($YES + "*") -and $Name -like ("*" + $AND + "*")) {
        return $true
    }
    return ($Name -like ($YES + "*") -and $Name -like "*且*") -or
        $Name -match ("^2[\." + [regex]::Escape($IDEOGRAPHIC_DOT) + "]?\s*" + [regex]::Escape($YES))
}

function Is-SubmitName([string]$Name) {
    return $Name -eq $SUBMIT -or $Name -like ($SUBMIT + "*")
}

function Is-ChoiceNumberName([string]$Name, [string]$Number) {
    return $Name -match ("^" + [regex]::Escape($Number) + "[\." + [regex]::Escape($IDEOGRAPHIC_DOT) + "]")
}

function Clean-ConversationTitle([string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Name)) {
        return ""
    }
    $waitingApproval = -join @([char]0x7B49, [char]0x5F85, [char]0x6279, [char]0x51C6)
    $ellipsisChar = [string][char]0x2026
    $title = ($Name -replace "\s+", " ").Trim()
    $title = $title.Replace($waitingApproval, "")
    $title = $title -replace "\s*\d+\s*\p{IsCJKUnifiedIdeographs}{1,2}$", ""
    $title = $title.Trim()
    if ($title.Length -gt 60) {
        $ellipsis = $title.IndexOf($ellipsisChar)
        if ($ellipsis -gt 4) {
            $title = $title.Substring(0, $ellipsis + 1)
        } else {
            $title = $title.Substring(0, 60)
        }
    }
    return $title.Trim()
}

function Is-ConversationTitleCandidate([string]$Name) {
    $title = Clean-ConversationTitle $Name
    if ([string]::IsNullOrWhiteSpace($title) -or $title.Length -lt 2) {
        return $false
    }
    $englishPaper = -join @([char]0x82F1, [char]0x8BED, [char]0x8BBA, [char]0x6587)
    $askAllow = -join @([char]0x662F, [char]0x5426, [char]0x5141, [char]0x8BB8)
    if ($title -eq "Codex" -or $title -eq $englishPaper) {
        return $false
    }
    if ($title.Contains($askAllow)) {
        return $false
    }
    if ($title -match "Copy-Item|New-Item|Remove-Item|Get-ChildItem|powershell|cmd\.exe|git |npm |curl|python|\.pptx|\.docx|[A-Z]:\\") {
        return $false
    }
    return $true
}
function Get-ConversationTitle($window, $scope) {
    $scopeRect = $scope.Current.BoundingRectangle
    $items = Get-VisibleElements $window

    $mainCandidates = @()
    foreach ($item in $items) {
        if ($item.Type -ne "ControlType.Text" -and $item.Type -ne "ControlType.ListItem") {
            continue
        }
        if (-not (Is-ConversationTitleCandidate $item.Name)) {
            continue
        }
        $rect = $item.Rect
        $sameColumn = ($rect.Right -gt ($scopeRect.Left - 80)) -and ($rect.Left -lt ($scopeRect.Right + 80))
        $aboveApproval = $rect.Top -lt $scopeRect.Top
        if ($sameColumn -and $aboveApproval) {
            $mainCandidates += [PSCustomObject]@{
                Name = (Clean-ConversationTitle $item.Name)
                Bottom = $rect.Bottom
            }
        }
    }
    if ($mainCandidates.Count -gt 0) {
        return ($mainCandidates | Sort-Object Bottom -Descending | Select-Object -First 1).Name
    }

    $waitingCandidates = @()
    foreach ($item in $items) {
        if ($item.Type -ne "ControlType.ListItem" -and $item.Type -ne "ControlType.Button") {
            continue
        }
        if ($item.Name -notlike "*等待批准*") {
            continue
        }
        $title = Clean-ConversationTitle $item.Name
        if (Is-ConversationTitleCandidate $title) {
            $waitingCandidates += [PSCustomObject]@{
                Name = $title
                Top = $item.Rect.Top
                Length = $title.Length
            }
        }
    }
    if ($waitingCandidates.Count -eq 1) {
        return $waitingCandidates[0].Name
    }
    if ($waitingCandidates.Count -gt 1) {
        return ($waitingCandidates | Sort-Object -Property @{ Expression = "Length"; Descending = $true }, @{ Expression = "Top"; Ascending = $true } | Select-Object -First 1).Name
    }
    return ""
}

function Select-ChoiceElement($items, [string]$Action) {
    if ($Action -eq "approve") {
        $matches = @($items | Where-Object { Is-YesName $_.Name })
        $choice = $matches | Where-Object { $_.Type -eq "ControlType.RadioButton" } | Select-Object -First 1
    } elseif ($Action -eq "approve-always") {
        $matches = @($items | Where-Object { Is-RememberName $_.Name })
        $choice = $matches | Where-Object { $_.Type -eq "ControlType.RadioButton" } | Select-Object -First 1
    } else {
        $matches = @($items | Where-Object { Is-NoName $_.Name })
        $choice = $matches | Where-Object { $_.Type -eq "ControlType.Edit" } | Select-Object -First 1
        if (-not $choice) {
            $choice = $matches | Where-Object { $_.Type -eq "ControlType.RadioButton" } | Select-Object -First 1
        }
    }
    if (-not $choice) {
        $choice = $matches | Select-Object -First 1
    }
    return $choice
}

function Get-ElementKey($element) {
    try {
        return ($element.GetRuntimeId() | ForEach-Object { $_.ToString() }) -join "."
    } catch {
        return [System.Runtime.CompilerServices.RuntimeHelpers]::GetHashCode($element).ToString()
    }
}

function Scope-HasApprovalControls($scope) {
    $items = @()
    $self = New-VisibleElementItem $scope
    if ($null -ne $self) {
        $items += $self
    }
    $items += Get-VisibleElements $scope
    $hasSubmit = @($items | Where-Object { $_.Type -eq "ControlType.Button" -and (Is-SubmitName $_.Name) }).Count -gt 0
    $hasSkip = @($items | Where-Object { $_.Type -eq "ControlType.Button" -and $_.Name -like ("*" + $SKIP + "*") }).Count -gt 0
    $hasYes = @($items | Where-Object { $_.Type -eq "ControlType.RadioButton" -and (Is-YesName $_.Name) }).Count -gt 0
    $hasNo = @($items | Where-Object { ($_.Type -eq "ControlType.Edit" -or $_.Type -eq "ControlType.RadioButton" -or $_.Type -eq "ControlType.Text") -and (Is-NoName $_.Name) }).Count -gt 0
    return $hasSubmit -and $hasSkip -and $hasYes -and $hasNo
}

function Get-ApprovalScopes($window) {
    $all = $window.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.Condition]::TrueCondition
    )
    $scopes = @()
    $seen = @{}
    foreach ($element in $all) {
        if ($element.Current.IsOffscreen) {
            continue
        }
        if ($element.Current.ControlType.ProgrammaticName -eq "ControlType.Group") {
            $name = ($element.Current.Name -replace "\s+", " ").Trim()
            if (
                $name -like ("*" + $SKIP + "*") -and
                $name -like ("*" + $SUBMIT + "*") -and
                ($name -like ("*" + $NO + "*")) -and
                (Scope-HasApprovalControls $element)
            ) {
                $key = Get-ElementKey $element
                if (-not $seen.ContainsKey($key)) {
                    $seen[$key] = $true
                    $scopes += $element
                }
            }
            continue
        }
        if ($element.Current.ControlType.ProgrammaticName -ne "ControlType.Button") {
            continue
        }
        $buttonName = ($element.Current.Name -replace "\s+", " ").Trim()
        if (-not (Is-SubmitName $buttonName)) {
            continue
        }
        $current = $element
        for ($i = 0; $i -lt 10 -and $null -ne $current; $i++) {
            $type = $current.Current.ControlType.ProgrammaticName
            if ($type -eq "ControlType.Group" -or $type -eq "ControlType.Pane" -or $type -eq "ControlType.Custom") {
                if (Scope-HasApprovalControls $current) {
                    $key = Get-ElementKey $current
                    if (-not $seen.ContainsKey($key)) {
                        $seen[$key] = $true
                        $scopes += $current
                    }
                    break
                }
            }
            $current = [System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($current)
        }
    }
    return $scopes
}

function Get-ApprovalDetailsForScope($window, $scope, [bool]$IncludeItems) {
    $items = @()
    $self = New-VisibleElementItem $scope
    if ($null -ne $self) {
        $items += $self
    }
    $items += Get-VisibleElements $scope
    $names = @($items | ForEach-Object { $_.Name })
    $hasSubmit = @($items | Where-Object { $_.Type -eq "ControlType.Button" -and (Is-SubmitName $_.Name) }).Count -gt 0
    $hasSkip = @($items | Where-Object { $_.Type -eq "ControlType.Button" -and $_.Name -like ("*" + $SKIP + "*") }).Count -gt 0
    $hasYes = @($items | Where-Object { $_.Type -eq "ControlType.RadioButton" -and (Is-YesName $_.Name) }).Count -gt 0
    $hasRemember = @($names | Where-Object { Is-RememberName $_ }).Count -gt 0
    $hasNo = @($names | Where-Object { Is-NoName $_ }).Count -gt 0
    if (-not ($hasSubmit -and $hasSkip -and $hasYes -and $hasNo)) {
        return $null
    }

    $interesting = @()
    foreach ($name in $names) {
        if (
            $name -match "New-Item|Copy-Item|curl|powershell|python|cmd|git|npm|Remove-Item|Invoke-WebRequest|cmake|ninja" -or
            (Is-SubmitName $name) -or
            $name -like ("*" + $SKIP + "*") -or
            (Is-YesName $name) -or
            (Is-RememberName $name) -or
            (Is-NoName $name) -or
            (Is-ChoiceNumberName $name "1") -or
            (Is-ChoiceNumberName $name "2") -or
            (Is-ChoiceNumberName $name "3")
        ) {
            $interesting += $name
        }
    }
    if ($interesting.Count -eq 0) {
        $interesting = $names | Select-Object -Last 40
    }
    $prompt = ($interesting | Select-Object -Last 40) -join "`n"
    $handle = [int]$window.Current.NativeWindowHandle
    $fingerprint = $handle.ToString() + "`n" + $prompt
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($fingerprint)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $signature = -join ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") })

    $details = [PSCustomObject]@{
        found = $true
        signature = $signature
        window_handle = $handle
        window_name = $window.Current.Name
        conversation_title = (Get-ConversationTitle $window $scope)
        prompt = $prompt
        can_approve_always = $hasRemember
    }
    if ($IncludeItems) {
        $details | Add-Member -NotePropertyName Items -NotePropertyValue $items
        $details | Add-Member -NotePropertyName Window -NotePropertyValue $window
    }
    return $details
}

function Get-ApprovalDetails($window, [bool]$IncludeItems) {
    foreach ($scope in Get-ApprovalScopes $window) {
        $details = Get-ApprovalDetailsForScope $window $scope $IncludeItems
        if ($null -ne $details) {
            return $details
        }
    }
    return $null
}

function Find-Approvals([bool]$IncludeItems) {
    $approvals = @()
    foreach ($window in Get-CodexWindows) {
        $details = Get-ApprovalDetails $window $IncludeItems
        if ($null -ne $details) {
            $approvals += $details
        }
    }
    return $approvals
}

function Click-Element($element) {
    $rect = $element.Current.BoundingRectangle
    if ($rect.IsEmpty) {
        return $false
    }
    $x = [int]($rect.Left + ($rect.Width / 2))
    $y = [int]($rect.Top + ($rect.Height / 2))
    [MouseNative]::SetCursorPos($x, $y) | Out-Null
    Start-Sleep -Milliseconds 80
    [MouseNative]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    [MouseNative]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
    return $true
}

function Select-Element($element) {
    try {
        $element.SetFocus()
    } catch {
    }
    try {
        $pattern = $element.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
        $pattern.Select()
        return $true
    } catch {
    }
    try {
        $pattern = $element.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
        if ($pattern.Current.ToggleState -ne [System.Windows.Automation.ToggleState]::On) {
            $pattern.Toggle()
        }
        return $true
    } catch {
    }
    return Click-Element $element
}

function Invoke-Element($element) {
    try {
        $element.SetFocus()
    } catch {
    }
    try {
        $pattern = $element.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
        $pattern.Invoke()
        return $true
    } catch {
    }
    return Click-Element $element
}

function Test-ApprovalStillVisible([string]$Signature) {
    foreach ($approval in Find-Approvals $false) {
        if ($approval.signature -eq $Signature) {
            return $true
        }
    }
    return $false
}

function Invoke-ApprovalAction([string]$Action, [string]$TargetSignature) {
    $matches = @()
    foreach ($approval in Find-Approvals $true) {
        if ([string]::IsNullOrWhiteSpace($TargetSignature) -or $approval.signature -eq $TargetSignature) {
            $matches += $approval
        }
    }
    if ($matches.Count -eq 0) {
        return [PSCustomObject]@{ ok = $false; error = "Target UI approval not found." }
    }
    if ([string]::IsNullOrWhiteSpace($TargetSignature) -and $matches.Count -gt 1) {
        return [PSCustomObject]@{ ok = $false; error = "Multiple UI approvals are visible. Use a specific ui approval id." }
    }

    $approval = $matches | Select-Object -First 1
    try {
        $approval.Window.SetFocus()
    } catch {
    }
    $items = $approval.Items
    $choice = Select-ChoiceElement $items $Action
    $submitElement = $items | Where-Object { Is-SubmitName $_.Name } | Select-Object -First 1
    if (-not $choice -or -not $submitElement) {
        return [PSCustomObject]@{ ok = $false; error = "UI approval option or submit button not found." }
    }
    Select-Element $choice.Element | Out-Null
    Start-Sleep -Milliseconds 250
    Invoke-Element $submitElement.Element | Out-Null
    Start-Sleep -Milliseconds 900
    if (Test-ApprovalStillVisible $approval.signature) {
        Click-Element $submitElement.Element | Out-Null
        Start-Sleep -Milliseconds 900
    }
    if (Test-ApprovalStillVisible $approval.signature) {
        return [PSCustomObject]@{ ok = $false; error = "UI approval is still visible after selecting and submitting."; signature = $approval.signature; window_handle = $approval.window_handle }
    }
    return [PSCustomObject]@{ ok = $true; error = ""; signature = $approval.signature; window_handle = $approval.window_handle }
}

if ($Mode -eq "detect") {
    $approvals = @(Find-Approvals $false)
    if ($approvals.Count -eq 0) {
        @{ found = $false; approvals = @() } | ConvertTo-Json -Compress
    } else {
        $first = $approvals | Select-Object -First 1
        @{
            found = $true
            approvals = $approvals
            signature = $first.signature
            window_handle = $first.window_handle
            window_name = $first.window_name
            prompt = $first.prompt
            can_approve_always = $first.can_approve_always
        } | ConvertTo-Json -Compress -Depth 4
    }
} else {
    Invoke-ApprovalAction $Mode $Signature | ConvertTo-Json -Compress
}
