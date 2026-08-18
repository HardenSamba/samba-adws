[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $Server,
    [Parameter(Mandatory = $false)] [pscredential] $Credential,
    [Parameter(Mandatory = $false)] [string] $OutputDirectory = ".\adws-test-results",
    [Parameter(Mandatory = $false)] [string] $TestUserPrefix = "adwsTest",
    [Parameter(Mandatory = $false)] [switch] $SkipMutations,
    [Parameter(Mandatory = $false)] [switch] $SkipStress
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

if (-not $Credential) { $Credential = Get-Credential -Message "Domain admin credentials" }
if (-not (Test-Path $OutputDirectory)) { New-Item -ItemType Directory -Path $OutputDirectory | Out-Null }

$timestamp  = Get-Date -Format "yyyyMMdd-HHmmss"
$logFile    = Join-Path $OutputDirectory "adws-test-$timestamp.log"
$jsonFile   = Join-Path $OutputDirectory "adws-test-$timestamp.json"
$results    = [System.Collections.Generic.List[object]]::new()

function Write-Section($title) {
    $bar = "=" * 70
    Add-Content -Path $logFile -Value "`r`n$bar`r`n  $title`r`n$bar"
    Write-Host "`n$bar" -ForegroundColor Cyan
    Write-Host "  $title" -ForegroundColor Cyan
    Write-Host $bar -ForegroundColor Cyan
}

function Invoke-Test {
    param(
        [string] $Name,
        [string] $Category,
        [scriptblock] $Action
    )
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $entry = [ordered]@{
        Name      = $Name
        Category  = $Category
        StartTime = (Get-Date).ToString("o")
        Status    = "Running"
        DurationMs = $null
        Output    = $null
        Error     = $null
    }
    Add-Content -Path $logFile -Value "`r`n--- TEST: [$Category] $Name ---"
    Write-Host "  [$Category] $Name ... " -NoNewline
    try {
        $output = & $Action 2>&1
        $sw.Stop()
        $entry.DurationMs = $sw.ElapsedMilliseconds
        $entry.Output     = ($output | Out-String).Trim()
        $entry.Status     = "Pass"
        Add-Content -Path $logFile -Value "STATUS: PASS ($($sw.ElapsedMilliseconds) ms)"
        Add-Content -Path $logFile -Value "OUTPUT:`r`n$($entry.Output)"
        Write-Host "PASS" -ForegroundColor Green -NoNewline
        Write-Host " ($($sw.ElapsedMilliseconds) ms)"
    } catch {
        $sw.Stop()
        $entry.DurationMs = $sw.ElapsedMilliseconds
        $entry.Status     = "Fail"
        $entry.Error      = $_.Exception.Message
        Add-Content -Path $logFile -Value "STATUS: FAIL ($($sw.ElapsedMilliseconds) ms)"
        Add-Content -Path $logFile -Value "ERROR: $($_.Exception.Message)"
        Add-Content -Path $logFile -Value "STACK: $($_.ScriptStackTrace)"
        Write-Host "FAIL" -ForegroundColor Red -NoNewline
        Write-Host " - $($_.Exception.Message)" -ForegroundColor DarkRed
    }
    $results.Add([pscustomobject]$entry) | Out-Null
}

function Run-Common {
    Import-Module ActiveDirectory -ErrorAction Stop
    Write-Section "Phase 1 - Connectivity"

    Invoke-Test "Get-ADRootDSE" "Connectivity" {
        Get-ADRootDSE -Server $Server | Format-List
    }
    Invoke-Test "Get-ADDomain" "Connectivity" {
        Get-ADDomain -Server $Server -Credential $Credential | Format-List
    }
    Invoke-Test "Get-ADForest" "Connectivity" {
        Get-ADForest -Server $Server -Credential $Credential | Format-List
    }
    Invoke-Test "Get-ADDomainController" "Connectivity" {
        Get-ADDomainController -Server $Server -Credential $Credential | Format-List
    }
}

function Run-Reads {
    Write-Section "Phase 2 - Read operations (WS-Transfer Get)"

    Invoke-Test "Get-ADUser Administrator -Properties *" "Read" {
        Get-ADUser Administrator -Server $Server -Credential $Credential -Properties *
    }
    Invoke-Test "Get-ADGroup 'Domain Admins'" "Read" {
        Get-ADGroup "Domain Admins" -Server $Server -Credential $Credential -Properties *
    }
    Invoke-Test "Get-ADComputer -Filter *" "Read" {
        Get-ADComputer -Filter * -Server $Server -Credential $Credential | Select-Object -First 5
    }
}

function Run-Enumerations {
    Write-Section "Phase 3 - Enumerations and filters (Enumerate / Pull / Search)"

    Invoke-Test "Get-ADUser -Filter * (full enumeration)" "Enumerate" {
        $users = Get-ADUser -Filter * -Server $Server -Credential $Credential
        "User count: $($users.Count)"
    }
    Invoke-Test "Get-ADUser AND filter" "Enumerate" {
        Get-ADUser -Filter "Enabled -eq 'True'" -Server $Server -Credential $Credential |
            Measure-Object | Select-Object Count
    }
    Invoke-Test "Get-ADUser LDAPFilter (OR + bitwise NOT)" "Enumerate" {
        Get-ADUser -LDAPFilter "(|(samAccountName=admin*)(!(userAccountControl:1.2.840.113556.1.4.803:=2)))" `
                   -Server $Server -Credential $Credential |
            Measure-Object | Select-Object Count
    }
    Invoke-Test "Get-ADObject paged enumeration" "Enumerate" {
        Get-ADObject -Filter * -Server $Server -Credential $Credential -ResultPageSize 50 |
            Measure-Object | Select-Object Count
    }
}

function Run-Mutations {
    Write-Section "Phase 4 - Mutations (Create / Put / Delete)"
    $userName = "$TestUserPrefix-User"
    $pw = ConvertTo-SecureString "P@ssw0rd!Test123" -AsPlainText -Force

    Invoke-Test "New-ADUser $userName" "Create" {
        New-ADUser -Name $userName -SamAccountName $userName -AccountPassword $pw -Enabled $true `
                   -Server $Server -Credential $Credential
        Get-ADUser $userName -Server $Server -Credential $Credential
    }
    Invoke-Test "Set-ADUser DisplayName + Description" "Modify" {
        Set-ADUser $userName -DisplayName "ADWS Test" -Description "Created by test" `
                   -Server $Server -Credential $Credential
        Get-ADUser $userName -Properties DisplayName, Description -Server $Server -Credential $Credential
    }
    Invoke-Test "Set-ADUser -Replace multi-attribute" "Modify" {
        Set-ADUser $userName -Replace @{title = "Engineer"; department = "QA"} `
                   -Server $Server -Credential $Credential
        Get-ADUser $userName -Properties title, department -Server $Server -Credential $Credential
    }
    # Non-ASCII write: guards the WCF decode "undefined entity" accent bug.
    # Built with [char]0xE9 so the test data is independent of this file's encoding.
    Invoke-Test "Set-ADUser non-ASCII / i18n round-trip" "Modify" {
        $e     = [char]0xE9
        $desc  = "cr${e}${e} via ADWS souverain"
        $title = "Ing${e}nieur R${e}seau"
        Set-ADUser $userName -Description $desc -Replace @{title = $title} `
                   -Server $Server -Credential $Credential
        $u = Get-ADUser $userName -Properties Description, title -Server $Server -Credential $Credential
        if ($u.Description -ne $desc -or $u.title -ne $title) {
            throw "i18n round-trip mismatch: Description='$($u.Description)' title='$($u.title)'"
        }
        $u
    }
    Invoke-Test "Remove-ADUser $userName" "Delete" {
        Remove-ADUser $userName -Confirm:$false -Server $Server -Credential $Credential
    }
}

function Run-Passwords {
    Write-Section "Phase 5 - Password operations (SetPassword / ChangePassword)"
    $userName = "$TestUserPrefix-Pwd"
    $pw       = ConvertTo-SecureString "P@ssw0rd!Test123" -AsPlainText -Force
    $resetPw  = ConvertTo-SecureString "Reset@1234"        -AsPlainText -Force
    $changedPw= ConvertTo-SecureString "Changed@5678"      -AsPlainText -Force

    Invoke-Test "Create user $userName" "Setup" {
        New-ADUser -Name $userName -SamAccountName $userName -AccountPassword $pw -Enabled $true `
                   -Server $Server -Credential $Credential
    }
    Invoke-Test "Set-ADAccountPassword -Reset" "SetPassword" {
        Set-ADAccountPassword $userName -Reset -NewPassword $resetPw `
                              -Server $Server -Credential $Credential
    }
    Invoke-Test "Set-ADAccountPassword (Change with old)" "ChangePassword" {
        Set-ADAccountPassword $userName -OldPassword $resetPw -NewPassword $changedPw `
                              -Server $Server -Credential $Credential
    }
    Invoke-Test "Cleanup $userName" "Cleanup" {
        Remove-ADUser $userName -Confirm:$false -Server $Server -Credential $Credential
    }
}

function Run-Groups {
    Write-Section "Phase 6 - Group operations"
    $groupName = "$TestUserPrefix-Group"
    $userA     = "$TestUserPrefix-MemberA"
    $userB     = "$TestUserPrefix-MemberB"
    $pw        = ConvertTo-SecureString "P@ssw0rd!Test123" -AsPlainText -Force

    Invoke-Test "Create group + 2 members" "Setup" {
        New-ADGroup -Name $groupName -GroupScope Global -Server $Server -Credential $Credential
        New-ADUser  -Name $userA -SamAccountName $userA -AccountPassword $pw -Enabled $true -Server $Server -Credential $Credential
        New-ADUser  -Name $userB -SamAccountName $userB -AccountPassword $pw -Enabled $true -Server $Server -Credential $Credential
    }
    Invoke-Test "Add-ADGroupMember" "GroupModify" {
        Add-ADGroupMember $groupName -Members $userA, $userB -Server $Server -Credential $Credential
    }
    Invoke-Test "Get-ADGroupMember (direct)" "GroupRead" {
        Get-ADGroupMember $groupName -Server $Server -Credential $Credential
    }
    Invoke-Test "Get-ADGroupMember -Recursive" "GroupRead" {
        Get-ADGroupMember $groupName -Recursive -Server $Server -Credential $Credential
    }
    Invoke-Test "Get-ADPrincipalGroupMembership" "GroupRead" {
        Get-ADPrincipalGroupMembership $userA -Server $Server -Credential $Credential
    }
    Invoke-Test "Remove-ADGroupMember + cleanup" "Cleanup" {
        Remove-ADGroupMember $groupName -Members $userA, $userB -Confirm:$false -Server $Server -Credential $Credential
        Remove-ADUser  $userA -Confirm:$false -Server $Server -Credential $Credential
        Remove-ADUser  $userB -Confirm:$false -Server $Server -Credential $Credential
        Remove-ADGroup $groupName -Confirm:$false -Server $Server -Credential $Credential
    }
}

function Run-Schema {
    Write-Section "Phase 7 - Schema discovery"
    $schemaNc = (Get-ADRootDSE -Server $Server).schemaNamingContext

    Invoke-Test "List 10 classSchema" "Schema" {
        Get-ADObject -SearchBase $schemaNc -LDAPFilter "(objectClass=classSchema)" `
                     -Server $Server -Credential $Credential -ResultPageSize 50 |
            Select-Object Name | Select-Object -First 10
    }
    Invoke-Test "List 10 attributeSchema" "Schema" {
        Get-ADObject -SearchBase $schemaNc -LDAPFilter "(objectClass=attributeSchema)" `
                     -Server $Server -Credential $Credential -ResultPageSize 50 |
            Select-Object Name | Select-Object -First 10
    }
}

function Run-Stress {
    Write-Section "Phase 8 - Stress (parallel reads, enumeration cache)"
    Invoke-Test "50 parallel Get-ADUser -Filter * (throttle 10)" "Stress" {
        $errors = 0
        1..50 | ForEach-Object -Parallel {
            try   { Get-ADUser -Filter * -Server $using:Server -Credential $using:Credential | Out-Null }
            catch { Write-Output "ERR: $($_.Exception.Message)" }
        } -ThrottleLimit 10 | ForEach-Object {
            if ($_ -like "ERR:*") { $script:errors++ ; Write-Output $_ }
        }
        "Errors: $errors / 50"
    }
}

function Write-Summary {
    $total = $results.Count
    $pass  = ($results | Where-Object { $_.Status -eq "Pass" }).Count
    $fail  = $total - $pass
    $summary = [ordered]@{
        Server      = $Server
        StartedAt   = ($results | Select-Object -First 1).StartTime
        Total       = $total
        Pass        = $pass
        Fail        = $fail
        LogFile     = $logFile
        ResultsFile = $jsonFile
        Tests       = $results
    }
    $summary | ConvertTo-Json -Depth 6 | Set-Content -Path $jsonFile -Encoding UTF8
    Write-Section "Summary"
    Write-Host "  Total: $total   Pass: $pass   Fail: $fail" -ForegroundColor Yellow
    Write-Host "  Log : $logFile"
    Write-Host "  JSON: $jsonFile"
    Add-Content -Path $logFile -Value "`r`nSUMMARY  Total=$total  Pass=$pass  Fail=$fail"
}

Write-Section "ADWS Sovereign Test Suite"
Add-Content -Path $logFile -Value "ADWS Sovereign Test Suite"
Add-Content -Path $logFile -Value "Server: $Server"
Add-Content -Path $logFile -Value "Started: $(Get-Date -Format o)"
Add-Content -Path $logFile -Value "User: $($Credential.UserName)"

Run-Common
Run-Reads
Run-Enumerations
if (-not $SkipMutations) {
    Run-Mutations
    Run-Passwords
    Run-Groups
}
Run-Schema
if (-not $SkipStress) { Run-Stress }
Write-Summary
