param(
    [Parameter(Mandatory = $true)]
    [string]$CommitMessage
)

# Ensure git is available
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "Git is not installed or not available in PATH."
    exit 1
}

# Stage all changes
git add .

# Commit with the provided message
git commit -m "$CommitMessage"

# Push to the current branch's upstream
git push -u origin main