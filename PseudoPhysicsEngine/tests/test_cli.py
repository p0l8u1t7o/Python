from typer.testing import CliRunner

from cellforge.cli import app

runner = CliRunner()


def test_cell_init_creates_git_project(tmp_path):
    project = tmp_path / "new-project"
    result = runner.invoke(app, ["init", str(project), "--json"])
    assert result.exit_code == 0, result.output
    assert (project / ".git").is_dir()
    assert (project / "project.yaml").is_file()
    assert (project / "viewer" / "theme").is_dir()
    validated = runner.invoke(app, ["validate", "--project", str(project), "--json"])
    assert validated.exit_code == 0, validated.output


def test_validation_failure_exit_code_is_two(tmp_path):
    result = runner.invoke(app, ["validate", "--project", str(tmp_path), "--json"])
    assert result.exit_code == 2
