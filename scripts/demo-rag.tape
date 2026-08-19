Output assets/demo-rag.gif

Set Shell "bash"
Set FontSize 15
Set Width 1100
Set Height 780
Set Padding 20
Set Theme "Catppuccin Mocha"

Hide
Type "source .venv/bin/activate && source ~/.zshrc && clear"
Enter
Sleep 500ms
Show

Type `pr-review-agent rag ask "How does the critic decide whether to escalate a finding?"`
Sleep 500ms
Enter
Sleep 20s
