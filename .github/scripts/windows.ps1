param([Parameter(Mandatory=$true)][ValidateSet("clean", "normalize")][string]$Phase)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:PRODUCT_NAME -cne 'UDP' -or $env:BASE_DIR -cne 'test') {
    throw 'Unexpected UDP native product/root'
}

function Optional-Item([string]$Path) {
    try { return Get-Item -LiteralPath $Path -Force -ErrorAction Stop }
    catch [System.Management.Automation.ItemNotFoundException] { return $null }
}

function Assert-Node([string]$Path, [bool]$Directory) {
    $item = Optional-Item $Path
    if ($null -eq $item) { return }
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Reparse output: $Path"
    }
    if ($item.PSIsContainer -ne $Directory) { throw "Wrong output type: $Path" }
    if ($Directory) {
        $null = @(Get-ChildItem -LiteralPath $Path -Force -ErrorAction Stop)
    } else {
        if ($null -ne $item.PSObject.Properties['UnixMode'] -and $item.UnixMode -match '^p|^s|^c|^b') {
            throw "Nonregular output: $Path"
        }
        $stream = [IO.File]::Open($item.FullName, 'Open', 'Read', 'Read')
        try { $null = $stream.ReadByte() } finally { $stream.Dispose() }
    }
}

function Assert-Ancestors([string]$Path) {
    $root = [IO.Path]::GetFullPath((Get-Location).Path)
    $full = [IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith($root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Output escapes checkout: $Path"
    }
    $parent = [IO.Path]::GetDirectoryName($full)
    while ($parent -ne $root) {
        Assert-Node $parent $true
        if ($null -ne (Optional-Item (Join-Path $parent '.git'))) {
            throw "Nested .git marker: $parent"
        }
        $parent = [IO.Path]::GetDirectoryName($parent)
    }
}

function Assert-Tree([string]$Path) {
    Assert-Node $Path $true
    if ($null -eq (Optional-Item $Path)) { return }
    foreach ($child in @(Get-ChildItem -LiteralPath $Path -Force -ErrorAction Stop)) {
        if ($child.Name -eq '.git') { throw "Nested .git marker: $($child.FullName)" }
        if ($child.PSIsContainer) {
            if ($child.Name -notin @('UDP.tlog')) { throw "Unexpected intermediate directory: $($child.FullName)" }
            Assert-Tree $child.FullName
        } else {
            if ($child.Name -notmatch '^(?:(?:4DPlugin-UDP|4DPlugin-JSON|4DPluginAPI|C_LONGINT|C_TEXT)\.obj|(?:vc\d+|UDP)\.pdb|UDP\.(?:exp|lib|log|vcxproj\.FileListAbsolute\.txt|lastbuildstate)|(?:CL|link|unsuccessfulbuild|UDP).+\.tlog)$') {
                throw "Unexpected intermediate file: $($child.FullName)"
            }
            Assert-Node $child.FullName $false
        }
    }
}

$canonical = 'test/Plugins/UDP.bundle/Contents/Windows64/UDP.4DX'
# Literal Release|x64 OutDir + default ProjectName + TargetExt in UDP.vcxproj.
$output = 'test/plugins/UDP.bundle/contents/windows64/UDP.4DX'
$intermediate = 'Objs/Release'
if ($Phase -eq 'clean') {
    Assert-Ancestors $canonical
    Assert-Node $canonical $false
    Assert-Ancestors $intermediate
    Assert-Tree $intermediate
    $indexed = & git ls-files -- $intermediate
    if ($LASTEXITCODE -ne 0) { throw 'Cannot validate intermediate index' }
    if ($indexed) { throw 'Tracked input inside Windows intermediate root' }
    $selected = & git ls-tree -r --name-only HEAD -- $intermediate
    if ($LASTEXITCODE -ne 0) { throw 'Cannot validate selected intermediate tree' }
    if ($selected) { throw 'Selected input inside Windows intermediate root' }
    # Finish validation of every target before the first removal.
    if ($null -ne (Optional-Item $canonical)) { Remove-Item -LiteralPath $canonical -Force -ErrorAction Stop }
    if ($null -ne (Optional-Item $intermediate)) { Remove-Item -LiteralPath $intermediate -Recurse -Force -ErrorAction Stop }
} else {
    Assert-Ancestors $output
    Assert-Node $output $false
    $source = Optional-Item $output
    if ($null -eq $source -or $source.Length -eq 0) { throw 'Missing or empty exact Release x64 UDP output' }
    Assert-Ancestors $canonical
    Assert-Node $canonical $false
    $destination = [IO.Path]::GetFullPath($canonical)
    if (-not [string]::Equals($source.FullName, $destination, [StringComparison]::OrdinalIgnoreCase)) {
        $null = New-Item -ItemType Directory -Force -Path ([IO.Path]::GetDirectoryName($destination))
        Copy-Item -LiteralPath $source.FullName -Destination $destination -Force -ErrorAction Stop
    }
}
