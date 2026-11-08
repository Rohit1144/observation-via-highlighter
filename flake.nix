{
  description = "Highlighter observations agent: mock MCP server + AgentCore harness client";

  inputs = {
    # Pinned to an exact commit by flake.lock (created on first `nix develop`).
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      # x86_64-linux covers WSL; aarch64 lets the same flake work on ARM machines/Macs.
      systems = [ "x86_64-linux" "aarch64-linux" "aarch64-darwin" "x86_64-darwin" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      devShells = forAllSystems (pkgs:
        let
          python = pkgs.python312.withPackages (ps: with ps; [
            mcp        # MCP Python SDK: our mock Highlighter MCP server + the client in the relay
            boto3      # AWS SDK: create_harness / invoke_harness
            pandas     # independent ground-truth calculations to check the agent's numbers
            pytest     # tests for the mock API and the verification script
          ]);
        in
        {
          default = pkgs.mkShell {
            packages = [
              python
              pkgs.awscli2   # IAM role setup, credential checks
              pkgs.jq        # inspecting JSON from the AWS CLI
            ];

            shellHook = ''
              # Keep Python from writing .pyc files into the repo and from picking up ~/.local packages.
              export PYTHONDONTWRITEBYTECODE=1
              export PYTHONNOUSERSITE=1
              echo "highlighter-agent dev shell: $(python --version), $(aws --version 2>&1 | cut -d' ' -f1)"
            '';
          };
        });
    };
}
