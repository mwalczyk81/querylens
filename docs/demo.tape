Output docs/assets/demo.gif

Set Shell "pwsh"
Set FontSize 16
Set Width 1400
Set Height 1100
Set Padding 20
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms

Hide
Env QUERYLENS_ENDPOINT "https://localhost:8081/"
Env QUERYLENS_COSMOS_KEY "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="
Show

Type "# Profile a workload against a Cosmos DB account"
Enter
Sleep 600ms
Type "uv run querylens run examples/workload.yaml"
Sleep 500ms
Enter
Sleep 10s

Ctrl+L
Type "# Stop early if the Request Unit budget is exceeded"
Enter
Sleep 600ms
Type "uv run querylens run examples/workload.yaml --ru-budget 30"
Sleep 500ms
Enter
Sleep 8s
