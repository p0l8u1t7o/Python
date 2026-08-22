"""The execution engine: branching, parallelism, timers, jumps and the caps.

A workflow moves real equipment, so the tests that matter most here are the
ones about *refusing* to move it: a condition that cannot be evaluated, a run
that loops forever, a device outside the workflow's site.
"""

from __future__ import annotations

import datetime as dt

from django.test import TestCase
from django.utils import timezone

from apps.telemetry.models import LatestSample
from apps.workflows.engine import advance
from apps.workflows.graph import GraphError, entry_nodes, validate_graph
from apps.workflows.models import RunStatus, Workflow, WorkflowLog
from apps.workflows.runner import ConcurrencyLimit, start_run, stop_run
from tests import factories


def node(node_id: str, node_type: str, **params) -> dict:
    return {"id": node_id, "type": node_type, "label": node_id, "params": params}


def edge(source: str, target: str, handle: str = "") -> dict:
    return {"source": source, "target": target, "source_handle": handle}


class EngineTestCase(TestCase):
    def setUp(self) -> None:
        self.org = factories.organization()
        self.site = factories.site(self.org, "plant")
        self.device = factories.device(self.org, "WF-BESS", site_obj=self.site)

    def make(self, nodes: list[dict], edges: list[dict], **kwargs) -> Workflow:
        return Workflow.objects.create(
            organization=self.org,
            name=kwargs.pop("name", "Test flow"),
            graph={"nodes": nodes, "edges": edges},
            **kwargs,
        )

    def reading(self, metric: str, value: float, *, age_seconds: float = 0) -> None:
        LatestSample.objects.update_or_create(
            organization=self.org,
            device=self.device,
            metric_key=metric,
            defaults={
                "value": value,
                "ts": timezone.now() - dt.timedelta(seconds=age_seconds),
                "quality": 0,
            },
        )

    def run_to_rest(self, workflow: Workflow, *, moment=None, passes: int = 20,
                    dry_run: bool = True, step_seconds: float = 5.0):
        """Run until it settles, advancing a virtual clock between passes.

        The clock has to move. A jump yields to the next tick and a holding
        timer re-samples on one, so calling ``advance`` repeatedly at the same
        instant would spin without ever reaching a wake time - which is the
        engine working as intended, not a test that needs more passes.

        Dry by default, for two reasons that both matter here. These tests
        assert on *which branch was taken*, and the step-by-step trace is kept
        in full only for test runs - a production run drops the debug lines so
        a loop does not write three rows a second forever. It also means
        nothing in this file can reach a device.
        """
        run = start_run(workflow, dry_run=dry_run)
        clock = moment or timezone.now()
        for _ in range(passes):
            advance(run, moment=clock)
            run.refresh_from_db()
            if not run.is_active:
                break
            clock += dt.timedelta(seconds=step_seconds)
        return run

    def messages(self, run) -> list[str]:
        return list(WorkflowLog.objects.filter(run=run).values_list("message", flat=True))


class BasicFlowTests(EngineTestCase):
    def test_a_straight_line_runs_to_the_end(self):
        workflow = self.make(
            [node("s", "start"), node("w", "node"), node("e", "end")],
            [edge("s", "w", "out"), edge("w", "e", "out")],
        )
        run = self.run_to_rest(workflow)
        self.assertEqual(run.status, RunStatus.SUCCEEDED)

    def test_a_disabled_node_is_stepped_over_not_executed(self):
        """The per-node switch comments a step out without redrawing edges."""
        nodes = [
            node("s", "start"),
            {**node("a", "send_action", device_id=str(self.device.id), command="reboot"),
             "enabled": False},
            node("e", "end"),
        ]
        run = self.run_to_rest(self.make(nodes, [edge("s", "a", "out"), edge("a", "e", "out")]))
        self.assertEqual(run.status, RunStatus.SUCCEEDED)
        self.assertIn("Skipped (disabled)", self.messages(run))

    def test_several_starts_run_as_parallel_branches(self):
        """Parallelism is drawn, not configured."""
        workflow = self.make(
            [node("s1", "start"), node("s2", "start"), node("w1", "node"),
             node("w2", "node"), node("e1", "end"), node("e2", "end")],
            [edge("s1", "w1", "out"), edge("w1", "e1", "out"),
             edge("s2", "w2", "out"), edge("w2", "e2", "out")],
        )
        self.assertEqual(sorted(entry_nodes(workflow.graph)), ["s1", "s2"])
        run = self.run_to_rest(workflow)
        self.assertEqual(run.status, RunStatus.SUCCEEDED)
        self.assertIn("with 2 branch(es)", self.messages(run)[0])

    def test_two_edges_from_one_handle_fork_the_branch(self):
        workflow = self.make(
            [node("s", "start"), node("a", "node"), node("b", "node"),
             node("e1", "end"), node("e2", "end")],
            [edge("s", "a", "out"), edge("s", "b", "out"),
             edge("a", "e1", "out"), edge("b", "e2", "out")],
        )
        run = self.run_to_rest(workflow)
        self.assertEqual(run.status, RunStatus.SUCCEEDED)
        visited = {log.node_id for log in WorkflowLog.objects.filter(run=run)}
        self.assertTrue({"a", "b"} <= visited)

    def test_a_graph_with_no_entry_point_is_refused_on_save(self):
        with self.assertRaises(GraphError):
            validate_graph({
                "nodes": [node("a", "node"), node("b", "node")],
                "edges": [edge("a", "b", "out"), edge("b", "a", "out")],
            })


class ConditionTests(EngineTestCase):
    def branch_taken(self, value: float | None, threshold: float, comparator="gt",
                     age_seconds: float = 0) -> str:
        if value is not None:
            self.reading("battery_soc", value, age_seconds=age_seconds)
        workflow = self.make(
            [
                node("s", "start"),
                node("c", "if_end", device_id=str(self.device.id),
                     metric_key="battery_soc", operator=comparator, threshold=threshold),
                node("t", "node"), node("f", "node"), node("u", "node"),
                node("e", "end"),
            ],
            [
                edge("s", "c", "out"),
                edge("c", "t", "true"), edge("c", "f", "false"), edge("c", "u", "unknown"),
                edge("t", "e", "out"), edge("f", "e", "out"), edge("u", "e", "out"),
            ],
            name=f"cond-{value}-{threshold}-{comparator}-{age_seconds}",
        )
        run = self.run_to_rest(workflow)
        visited = {log.node_id for log in WorkflowLog.objects.filter(run=run)}
        for candidate in ("t", "f", "u"):
            if candidate in visited:
                return candidate
        return ""

    def test_true_takes_the_true_branch(self):
        self.assertEqual(self.branch_taken(80.0, 50.0), "t")

    def test_false_takes_the_false_branch(self):
        self.assertEqual(self.branch_taken(20.0, 50.0), "f")

    def test_a_missing_reading_takes_neither(self):
        """An interlock that guesses is worse than one that stops."""
        self.assertEqual(self.branch_taken(None, 50.0), "u")

    def test_a_stale_reading_takes_neither(self):
        """A device that stopped reporting must not read as 'below threshold'."""
        self.assertEqual(self.branch_taken(20.0, 50.0, age_seconds=9999), "u")


class TimerTests(EngineTestCase):
    def build(self, hold_seconds: int = 30) -> Workflow:
        return self.make(
            [
                node("s", "start"),
                node("c", "if_end_timer", device_id=str(self.device.id),
                     metric_key="grid_power_w", operator="gt", threshold=500.0,
                     hold_seconds=hold_seconds),
                node("t", "node"), node("f", "node"), node("e", "end"),
            ],
            [
                edge("s", "c", "out"),
                edge("c", "t", "true"), edge("c", "f", "false"),
                edge("t", "e", "out"), edge("f", "e", "out"),
            ],
        )

    def test_a_condition_that_has_not_held_long_enough_waits(self):
        self.reading("grid_power_w", 900.0)
        run = start_run(self.build(30), dry_run=True)
        advance(run, moment=timezone.now())
        run.refresh_from_db()
        self.assertEqual(run.status, RunStatus.WAITING)
        self.assertIsNotNone(run.wake_at)

    def test_it_fires_once_the_condition_has_held(self):
        self.reading("grid_power_w", 900.0)
        start = timezone.now()
        run = start_run(self.build(30), dry_run=True)

        # Sampled repeatedly through the hold, then again once it has elapsed.
        clock = start
        for _ in range(30):
            advance(run, moment=clock)
            run.refresh_from_db()
            if not run.is_active:
                break
            clock += dt.timedelta(seconds=4)

        visited = {log.node_id for log in WorkflowLog.objects.filter(run=run)}
        self.assertIn("t", visited)

    def test_the_timer_restarts_when_the_condition_drops(self):
        """This is the whole point: a spike must not get through.

        And it is why the node re-samples rather than sleeping through the
        hold - looking once at the end cannot tell "true the entire time" from
        "dropped in the middle and came back".
        """
        self.reading("grid_power_w", 900.0)
        start = timezone.now()
        run = start_run(self.build(30), dry_run=True)
        advance(run, moment=start)

        # It drops well before the hold elapses.
        self.reading("grid_power_w", 100.0)
        advance(run, moment=start + dt.timedelta(seconds=10))
        run.refresh_from_db()

        visited = {log.node_id for log in WorkflowLog.objects.filter(run=run)}
        self.assertIn("f", visited)
        self.assertNotIn("t", visited)

    def test_a_condition_that_comes_back_does_not_count_as_having_held(self):
        """The failure a sleep-through implementation would let past."""
        self.reading("grid_power_w", 900.0)
        start = timezone.now()
        run = start_run(self.build(30), dry_run=True)
        advance(run, moment=start)

        self.reading("grid_power_w", 100.0)          # drops at t+5
        advance(run, moment=start + dt.timedelta(seconds=5))
        self.reading("grid_power_w", 900.0)          # returns at t+10
        advance(run, moment=start + dt.timedelta(seconds=10))
        run.refresh_from_db()

        # At t+31 the condition is true and 31s have passed since it first went
        # true - but it did not hold, so the true branch must not have fired.
        advance(run, moment=start + dt.timedelta(seconds=31))
        run.refresh_from_db()
        visited = {log.node_id for log in WorkflowLog.objects.filter(run=run)}
        self.assertNotIn("t", visited)


class JumpTests(EngineTestCase):
    def test_a_jump_continues_at_the_named_node(self):
        workflow = self.make(
            [node("s", "start"), node("j", "jump", target="far"),
             node("skipped", "node"), node("far", "node"), node("e", "end")],
            [edge("s", "j", "out"), edge("j", "skipped", "out"), edge("far", "e", "out")],
        )
        run = self.run_to_rest(workflow)
        visited = {log.node_id for log in WorkflowLog.objects.filter(run=run)}
        self.assertIn("far", visited)
        self.assertNotIn("skipped", visited)

    def test_a_jump_to_a_missing_node_is_refused_on_save(self):
        with self.assertRaises(GraphError):
            validate_graph({
                "nodes": [node("s", "start"), node("j", "jump", target="nowhere")],
                "edges": [edge("s", "j", "out")],
            })

    def test_a_loop_ticks_rather_than_spinning(self):
        """A jump backwards is a loop, and a loop run flat out is a busy-wait.

        It would burn the whole step budget in seconds, flood the log and
        hammer the database - all to re-read a value that changes every few
        seconds at most. So a jump yields to the next tick, which is also the
        semantic the operator drew: keep checking this.
        """
        workflow = self.make(
            [node("s", "start"), node("a", "node"), node("j", "jump", target="a")],
            [edge("s", "a", "out"), edge("a", "j", "out")],
        )
        run = start_run(workflow, dry_run=True)
        start = timezone.now()

        # Ten passes at the *same* instant must not advance a parked loop.
        for _ in range(10):
            advance(run, moment=start)
        run.refresh_from_db()
        first = run.steps_taken

        advance(run, moment=start + dt.timedelta(seconds=30))
        run.refresh_from_db()

        self.assertLess(first, 6, "the loop spun instead of parking")
        self.assertGreater(run.steps_taken, first, "the loop never resumed")
        self.assertTrue(run.is_active)

    def test_an_endless_loop_is_stopped_by_the_step_budget(self):
        """The tick slows a loop down; it does not bound it. A graph that can
        never finish still has to be caught, and a wall-clock limit would not
        catch a tight one."""
        workflow = self.make(
            [node("s", "start"), node("a", "node"), node("j", "jump", target="a")],
            [edge("s", "a", "out"), edge("a", "j", "out")],
        )
        with self.settings(WORKFLOWS={**self.settings_workflows(), "MAX_STEPS_PER_RUN": 25}):
            run = self.run_to_rest(workflow, passes=40, step_seconds=30)
        self.assertEqual(run.status, RunStatus.FAILED)
        self.assertIn("Step limit", run.error)

    @staticmethod
    def settings_workflows() -> dict:
        from django.conf import settings

        return dict(settings.WORKFLOWS)


class ConcurrencyTests(EngineTestCase):
    def test_the_cap_refuses_rather_than_queues(self):
        """A queue would build an invisible backlog of pending commands."""
        workflow = self.make([node("s", "start")], [])
        with self.settings(
            WORKFLOWS={**JumpTests.settings_workflows(), "MAX_CONCURRENT_RUNS": 2}
        ):
            start_run(workflow)
            start_run(workflow)
            with self.assertRaises(ConcurrencyLimit) as caught:
                start_run(workflow)
        self.assertEqual(caught.exception.details["limit"], 2)

    def test_stopping_a_run_frees_its_slot(self):
        workflow = self.make([node("s", "start")], [])
        with self.settings(
            WORKFLOWS={**JumpTests.settings_workflows(), "MAX_CONCURRENT_RUNS": 1}
        ):
            first = start_run(workflow)
            with self.assertRaises(ConcurrencyLimit):
                start_run(workflow)
            stop_run(first, reason="test")
            start_run(workflow)

    def test_a_disabled_workflow_cannot_be_started(self):
        workflow = self.make([node("s", "start")], [], is_enabled=False)
        from apps.core.errors import Conflict

        with self.assertRaises(Conflict):
            start_run(workflow)


class WaitNodeTests(EngineTestCase):
    def test_wait_parks_then_continues(self):
        workflow = self.make(
            [node("s", "start"), node("w", "wait", seconds=12), node("e", "end")],
            [edge("s", "w", "out"), edge("w", "e", "out")],
        )
        run = start_run(workflow, dry_run=True)
        clock = timezone.now()
        advance(run, moment=clock)
        run.refresh_from_db()
        # Parked, not finished - and parked for the full wait, not a poll.
        self.assertEqual(run.status, RunStatus.WAITING)
        self.assertGreaterEqual((run.wake_at - clock).total_seconds(), 11.5)

        # Waking early does not restart the clock.
        advance(run, moment=clock + dt.timedelta(seconds=6))
        run.refresh_from_db()
        self.assertEqual(run.status, RunStatus.WAITING)

        advance(run, moment=clock + dt.timedelta(seconds=13))
        run.refresh_from_db()
        advance(run, moment=clock + dt.timedelta(seconds=13))
        run.refresh_from_db()
        self.assertEqual(run.status, RunStatus.SUCCEEDED)


class ConditionWaitTests(EngineTestCase):
    def build(self, timeout: int = 60) -> Workflow:
        return self.make(
            [
                node("s", "start"),
                node("c", "condition_wait", device_id=str(self.device.id),
                     metric_key="battery_soc", operator="gt", threshold=50.0,
                     timeout_seconds=timeout),
                node("m", "node"), node("x", "node"), node("e", "end"),
            ],
            [
                edge("s", "c", "out"),
                edge("c", "m", "met"), edge("c", "x", "timeout"),
                edge("m", "e", "out"), edge("x", "e", "out"),
            ],
        )

    def visited(self, run) -> set[str]:
        return {log.node_id for log in WorkflowLog.objects.filter(run=run)}

    def test_takes_met_the_moment_the_condition_is_true(self):
        self.reading("battery_soc", 80.0)
        run = self.run_to_rest(self.build())
        self.assertEqual(run.status, RunStatus.SUCCEEDED)
        self.assertIn("m", self.visited(run))

    def test_waits_while_false_then_takes_met_when_it_turns(self):
        self.reading("battery_soc", 20.0)
        workflow = self.build(timeout=300)
        run = start_run(workflow, dry_run=True)
        clock = timezone.now()
        for _ in range(3):
            advance(run, moment=clock)
            run.refresh_from_db()
            clock += dt.timedelta(seconds=10)
        self.assertEqual(run.status, RunStatus.WAITING)

        self.reading("battery_soc", 80.0)
        for _ in range(3):
            advance(run, moment=clock)
            run.refresh_from_db()
            clock += dt.timedelta(seconds=10)
        self.assertEqual(run.status, RunStatus.SUCCEEDED)
        self.assertIn("m", self.visited(run))

    def test_times_out_when_the_condition_never_comes(self):
        self.reading("battery_soc", 20.0)
        run = self.run_to_rest(self.build(timeout=30), passes=30, step_seconds=10)
        self.assertEqual(run.status, RunStatus.SUCCEEDED)
        self.assertIn("x", self.visited(run))
        self.assertNotIn("m", self.visited(run))

    def test_a_missing_reading_waits_and_the_timeout_catches_it(self):
        """No reading is 'not met yet', not 'met' - the timeout is the exit."""
        run = self.run_to_rest(self.build(timeout=30), passes=30, step_seconds=10)
        self.assertEqual(run.status, RunStatus.SUCCEEDED)
        self.assertIn("x", self.visited(run))


class IfEndTimeTests(EngineTestCase):
    def build(self, *, days="everyday", start="09:00", end="18:00",
              wait_for_window=True, name="time-window") -> Workflow:
        return self.make(
            [
                node("s", "start"),
                node("c", "if_end_time", days=days, start_time=start, end_time=end,
                     wait_for_window=wait_for_window),
                node("t", "node"), node("f", "node"), node("e", "end"),
            ],
            [
                edge("s", "c", "out"),
                edge("c", "t", "true"), edge("c", "f", "false"),
                edge("t", "e", "out"), edge("f", "e", "out"),
            ],
            name=name,
        )

    def at(self, hour: int, minute: int = 0, *, weekday: int = 2) -> dt.datetime:
        """A UTC moment on a fixed week; weekday is ISO (1=Mon..7=Sun).

        2026-08-17 is a Monday. Site timezone defaults to UTC in the factory,
        so UTC wall clock IS the local wall clock here.
        """
        base = dt.datetime(2026, 8, 17, tzinfo=dt.UTC) + dt.timedelta(days=weekday - 1)
        return base.replace(hour=hour, minute=minute)

    def visited(self, run) -> set[str]:
        return {log.node_id for log in WorkflowLog.objects.filter(run=run)}

    def test_inside_the_window_takes_true(self):
        run = self.run_to_rest(self.build(), moment=self.at(10))
        self.assertEqual(run.status, RunStatus.SUCCEEDED)
        self.assertIn("t", self.visited(run))

    def test_outside_without_waiting_takes_false(self):
        run = self.run_to_rest(self.build(wait_for_window=False), moment=self.at(20))
        self.assertEqual(run.status, RunStatus.SUCCEEDED)
        self.assertIn("f", self.visited(run))

    def test_outside_with_waiting_parks_until_the_window_opens(self):
        workflow = self.build()
        run = start_run(workflow, dry_run=True)
        advance(run, moment=self.at(20))
        run.refresh_from_db()
        self.assertEqual(run.status, RunStatus.WAITING)
        # Parked until 09:00 the next day, not polling through the night.
        self.assertEqual(run.wake_at.astimezone(dt.UTC).hour, 9)
        self.assertEqual(run.wake_at.astimezone(dt.UTC).date(),
                         self.at(20).date() + dt.timedelta(days=1))

    def test_weekday_filter_is_respected(self):
        # Saturday, weekdays-only window, no waiting: false branch.
        run = self.run_to_rest(
            self.build(days="weekdays", wait_for_window=False, name="wd"),
            moment=self.at(10, weekday=6),
        )
        self.assertIn("f", self.visited(run))

    def test_a_window_across_midnight_covers_both_sides(self):
        for hour, expect in ((23, "t"), (2, "t"), (12, "f")):
            run = self.run_to_rest(
                self.build(start="22:00", end="06:00", wait_for_window=False,
                           name=f"night-{hour}"),
                moment=self.at(hour),
            )
            self.assertIn(expect, self.visited(run), f"at {hour}:00")


class NoteTests(EngineTestCase):
    def test_a_note_is_never_an_entry_point_and_never_runs(self):
        workflow = self.make(
            [node("s", "start"), node("e", "end"),
             {"id": "memo", "type": "note", "label": "memo",
              "params": {}, "text": "remember to breathe"}],
            [edge("s", "e", "out")],
        )
        self.assertEqual(entry_nodes(workflow.graph), ["s"])
        run = self.run_to_rest(workflow)
        self.assertEqual(run.status, RunStatus.SUCCEEDED)
        self.assertNotIn(
            "memo", {log.node_id for log in WorkflowLog.objects.filter(run=run)}
        )

    def test_an_edge_into_a_note_is_refused_but_an_arrow_from_one_is_not(self):
        # An arrow FROM a note is an annotation and saves fine.
        validate_graph({
            "nodes": [node("s", "start"), node("memo", "note"), node("e", "end")],
            "edges": [edge("s", "e", "out"), edge("memo", "e", "")],
        })
        # An edge INTO a note would look like flow; refused.
        with self.assertRaises(GraphError):
            validate_graph({
                "nodes": [node("s", "start"), node("memo", "note"), node("e", "end")],
                "edges": [edge("s", "memo", "out"), edge("s", "e", "out")],
            })

    def test_a_note_arrow_does_not_steal_an_entry_point(self):
        """A start-less sketch annotated by a note must still have entries."""
        graph = {
            "nodes": [node("a", "node"), node("e", "end"), node("memo", "note")],
            "edges": [edge("a", "e", "out"), edge("memo", "a", "")],
        }
        self.assertEqual(entry_nodes(graph), ["a"])

    def test_a_canvas_of_only_notes_saves_without_an_entry_point(self):
        validate_graph({"nodes": [node("memo", "note")], "edges": []})


class PauseResumeStepTests(EngineTestCase):
    def line(self, length: int = 3) -> Workflow:
        middles = [node(f"n{i}", "node") for i in range(length)]
        nodes_ = [node("s", "start"), *middles, node("e", "end")]
        ids = [n["id"] for n in nodes_]
        return self.make(nodes_, [edge(a, b, "out") for a, b in zip(ids, ids[1:])])

    def test_a_paused_run_does_not_move(self):
        from apps.workflows.runner import pause_run

        run = start_run(self.line(), dry_run=True)
        advance(run, moment=timezone.now(), step_budget=1)
        run.refresh_from_db()
        pause_run(run)
        steps_before = run.steps_taken
        advance(run, moment=timezone.now() + dt.timedelta(seconds=60))
        run.refresh_from_db()
        self.assertEqual(run.status, RunStatus.PAUSED)
        self.assertEqual(run.steps_taken, steps_before)

    def test_resume_continues_where_it_stood(self):
        from apps.workflows.runner import pause_run, resume_run

        run = start_run(self.line(), dry_run=True)
        advance(run, moment=timezone.now(), step_budget=1)
        run.refresh_from_db()
        pause_run(run)
        resume_run(run)
        run.refresh_from_db()
        clock = timezone.now()
        for _ in range(10):
            advance(run, moment=clock)
            run.refresh_from_db()
            if not run.is_active:
                break
            clock += dt.timedelta(seconds=5)
        self.assertEqual(run.status, RunStatus.SUCCEEDED)

    def test_step_executes_exactly_one_node_then_pauses(self):
        from apps.workflows.runner import step_run

        run = start_run(self.line(), start_paused=True, dry_run=True)
        self.assertEqual(run.status, RunStatus.PAUSED)
        steps = []
        for _ in range(10):
            run = step_run(run)
            steps.append(run.steps_taken)
            if run.status != RunStatus.PAUSED:
                break
        # Each press moved at most one transition; the last press executes
        # the End node, which removes the token without counting a move.
        self.assertTrue(all(b - a in (0, 1) for a, b in zip(steps, steps[1:])))
        self.assertEqual(run.status, RunStatus.SUCCEEDED)
        self.assertEqual(len(steps), 5)  # s, n0, n1, n2, e - one press each
        self.assertEqual(steps[-1], 4)

    def test_a_paused_run_still_occupies_a_slot(self):
        from django.conf import settings as dj_settings
        from django.test import override_settings

        from apps.workflows.runner import pause_run

        run = start_run(self.line(), dry_run=True)
        pause_run(run)
        wf2 = self.make(
            [node("s", "start"), node("e", "end")], [edge("s", "e", "out")],
            name="second",
        )
        patched = {**dj_settings.WORKFLOWS, "MAX_CONCURRENT_RUNS": 1}
        with override_settings(WORKFLOWS=patched):
            with self.assertRaises(ConcurrencyLimit):
                start_run(wf2, dry_run=True)


class BreakpointTests(EngineTestCase):
    def test_a_breakpoint_pauses_before_the_node_runs(self):
        from apps.workflows.runner import resume_run

        workflow = self.make(
            [node("s", "start"),
             {**node("b", "node"), "breakpoint": True},
             node("e", "end")],
            [edge("s", "b", "out"), edge("b", "e", "out")],
        )
        run = start_run(workflow, dry_run=True)
        clock = timezone.now()
        for _ in range(5):
            advance(run, moment=clock)
            run.refresh_from_db()
            if run.status == RunStatus.PAUSED:
                break
            clock += dt.timedelta(seconds=2)
        self.assertEqual(run.status, RunStatus.PAUSED)
        # Paused *at* the node, before executing it.
        self.assertEqual({t.node_id for t in run.tokens.all()}, {"b"})

        # Resume runs it once and does not re-trip the same breakpoint.
        resume_run(run)
        run.refresh_from_db()
        for _ in range(5):
            advance(run, moment=clock)
            run.refresh_from_db()
            if not run.is_active:
                break
            clock += dt.timedelta(seconds=2)
        self.assertEqual(run.status, RunStatus.SUCCEEDED)


class StepDelayTests(EngineTestCase):
    def test_a_delay_spaces_the_transitions_out(self):
        workflow = self.make(
            [node("s", "start"), node("w", "node"), node("e", "end")],
            [edge("s", "w", "out"), edge("w", "e", "out")],
        )
        run = start_run(workflow, dry_run=True, step_delay_seconds=5)
        clock = timezone.now()
        advance(run, moment=clock)
        run.refresh_from_db()
        # After one transition the run is parked for the delay, not barrelling on.
        self.assertEqual(run.status, RunStatus.WAITING)
        self.assertGreaterEqual((run.wake_at - clock).total_seconds(), 4.5)

    def test_single_step_sees_through_the_delay_but_not_a_wait(self):
        """Stepping ignores the viewing delay; a Wait node's own timer holds."""
        from apps.workflows.runner import step_run

        workflow = self.make(
            [node("s", "start"), node("w", "wait", seconds=300), node("e", "end")],
            [edge("s", "w", "out"), edge("w", "e", "out")],
            name="step-delay",
        )
        run = start_run(workflow, dry_run=True, step_delay_seconds=10,
                        start_paused=True)
        run = step_run(run)  # executes "s"; slow-motion parks the token
        self.assertEqual(run.steps_taken, 1)
        run = step_run(run)  # sees through the delay, executes "wait"
        self.assertEqual(run.steps_taken, 2)
        # The Wait node parked the token for its own 300s - stepping again
        # must NOT shorten that.
        before = run.steps_taken
        run = step_run(run)
        self.assertEqual(run.steps_taken, before)
        token = run.tokens.first()
        self.assertIsNotNone(token.wake_at)

    def test_the_delay_is_clamped(self):
        workflow = self.make(
            [node("s", "start"), node("e", "end")], [edge("s", "e", "out")],
            name="clamped",
        )
        run = start_run(workflow, dry_run=True, step_delay_seconds=9999)
        self.assertEqual(run.step_delay_seconds, 30.0)


class SingleNodeRunTests(EngineTestCase):
    def test_runs_exactly_the_chosen_node_and_finishes(self):
        from apps.workflows.runner import run_single_node

        workflow = self.make(
            [node("s", "start"), node("a", "node"), node("b", "node"),
             node("e", "end")],
            [edge("s", "a", "out"), edge("a", "b", "out"), edge("b", "e", "out")],
        )
        run = run_single_node(workflow, node_id="a", dry_run=True)
        self.assertEqual(run.status, RunStatus.SUCCEEDED)
        self.assertEqual(run.steps_taken, 1)
        visited = {log.node_id for log in WorkflowLog.objects.filter(run=run)}
        # Only the chosen node executed - the edge to "b" was not followed.
        self.assertIn("a", visited)
        self.assertNotIn("b", visited)
        self.assertEqual(run.tokens.count(), 0)

    def test_disabled_and_breakpoint_flags_are_ignored(self):
        from apps.workflows.runner import run_single_node

        workflow = self.make(
            [node("s", "start"),
             {**node("a", "node"), "enabled": False, "breakpoint": True},
             node("e", "end")],
            [edge("s", "a", "out"), edge("a", "e", "out")],
        )
        run = run_single_node(workflow, node_id="a", dry_run=True)
        self.assertEqual(run.status, RunStatus.SUCCEEDED)
        messages = self.messages(run)
        self.assertNotIn("Skipped (disabled)", messages)
        self.assertNotIn("Paused at breakpoint", messages)
        # The stored workflow keeps its flags - only the run copy was stripped.
        stored = next(n for n in workflow.graph["nodes"] if n["id"] == "a")
        self.assertIs(stored.get("enabled"), False)
        self.assertIs(stored.get("breakpoint"), True)

    def test_a_note_cannot_be_run(self):
        from apps.core.errors import Conflict
        from apps.workflows.runner import run_single_node

        workflow = self.make(
            [node("s", "start"), node("e", "end"), node("memo", "note")],
            [edge("s", "e", "out")],
        )
        with self.assertRaises(Conflict):
            run_single_node(workflow, node_id="memo", dry_run=True)


class LoopVisitOrderTests(EngineTestCase):
    def test_wait_wait_jump_loop_visits_nodes_in_drawn_order(self):
        """The DEMO shape: start -> wait 5s -> wait 2s -> jump to start."""
        workflow = self.make(
            [node("s", "start"), node("w5", "wait", seconds=5),
             node("w2", "wait", seconds=2), node("j", "jump", target="s")],
            [edge("s", "w5", "out"), edge("w5", "w2", "out"), edge("w2", "j", "out")],
        )
        run = start_run(workflow, dry_run=True)
        clock = timezone.now()
        positions = []
        for _ in range(40):
            advance(run, moment=clock)
            run.refresh_from_db()
            token = run.tokens.first()
            if token is None:
                break
            if not positions or positions[-1] != token.node_id:
                positions.append(token.node_id)
            clock += dt.timedelta(seconds=1)

        # Two full laps in the drawn order. The jump node never shows as a
        # resting place - it executes and forwards within one advance - so the
        # observable positions are the nodes that actually take time.
        joined = ">".join(positions)
        self.assertIn("w5>w2>s>w5>w2>s", joined)
        # The log still records the jump firing each lap.
        jumps = WorkflowLog.objects.filter(run=run, node_id="j").count()
        self.assertGreaterEqual(jumps, 2)


class BranchAccountingTests(EngineTestCase):
    """The concurrency unit is branches (tokens), not runs."""

    def two_branch_workflow(self, name="two-branch") -> Workflow:
        return self.make(
            [node("s1", "start"), node("s2", "start"),
             node("e1", "end"), node("e2", "end")],
            [edge("s1", "e1", "out"), edge("s2", "e2", "out")],
            name=name,
        )

    def test_a_two_branch_run_counts_as_two(self):
        from apps.workflows.runner import active_branches

        workflow = self.two_branch_workflow()
        run = start_run(workflow, dry_run=True, start_paused=True)
        self.assertEqual(run.tokens.count(), 2)
        self.assertEqual(active_branches(self.org), 2)

    def test_starting_is_refused_when_the_branches_would_not_fit(self):
        from django.conf import settings as dj_settings
        from django.test import override_settings

        line = self.make(
            [node("s", "start"), node("e", "end")], [edge("s", "e", "out")],
            name="one-branch",
        )
        wide = self.two_branch_workflow()

        patched = {**dj_settings.WORKFLOWS, "MAX_CONCURRENT_RUNS": 2}
        with override_settings(WORKFLOWS=patched):
            start_run(line, dry_run=True, start_paused=True)  # 1 of 2 used
            # A two-branch run needs 2 slots; only 1 remains.
            with self.assertRaises(ConcurrencyLimit):
                start_run(wide, dry_run=True)
            # A one-branch run still fits.
            second = self.make(
                [node("s", "start"), node("e", "end")], [edge("s", "e", "out")],
                name="one-branch-2",
            )
            run = start_run(second, dry_run=True, start_paused=True)
            self.assertEqual(run.tokens.count(), 1)


class ArrowDecorationTests(EngineTestCase):
    def test_an_arrow_is_pure_decoration(self):
        graph = {
            "nodes": [node("s", "start"), node("e", "end"),
                      node("a1", "arrow", direction="down")],
            "edges": [edge("s", "e", "out")],
        }
        validate_graph(graph)
        self.assertEqual(entry_nodes(graph), ["s"])
        # Nothing may connect into an arrow.
        with self.assertRaises(GraphError):
            validate_graph({
                "nodes": [node("s", "start"), node("e", "end"),
                          node("a1", "arrow", direction="down")],
                "edges": [edge("s", "e", "out"), edge("s", "a1", "out")],
            })


class BranchMergeTests(EngineTestCase):
    """Arrivals merge: one branch per node, or loops through forks explode."""

    def test_a_loop_through_a_fork_does_not_multiply_branches(self):
        """The exact shape that used to double the branch count every lap
        (2, 4, 8 ... until the step budget killed the run): both forks jump
        back to the forking start."""
        workflow = self.make(
            [node("s", "start"), node("a", "node"), node("b", "node"),
             node("j1", "jump", target="s"), node("j2", "jump", target="s")],
            [edge("s", "a", "out"), edge("s", "b", "out"),
             edge("a", "j1", "out"), edge("b", "j2", "out")],
        )
        run = start_run(workflow, dry_run=True)
        clock = timezone.now()
        peak = 0
        for _ in range(12):
            advance(run, moment=clock)
            run.refresh_from_db()
            peak = max(peak, run.tokens.count())
            clock += dt.timedelta(seconds=2)
        # Bounded by the number of nodes, not doubling per lap.
        self.assertLessEqual(peak, 5)
        self.assertEqual(run.status, RunStatus.WAITING)

    def test_two_branches_converging_execute_the_shared_tail_once(self):
        workflow = self.make(
            [node("s", "start"), node("a", "node"), node("b", "node"),
             node("m", "node"), node("e", "end")],
            [edge("s", "a", "out"), edge("s", "b", "out"),
             edge("a", "m", "out"), edge("b", "m", "out"), edge("m", "e", "out")],
        )
        run = self.run_to_rest(workflow)
        self.assertEqual(run.status, RunStatus.SUCCEEDED)
        # The merge point ran once, not once per inbound branch. (The merge
        # itself also logs against this node, so count executions, not rows.)
        visits = WorkflowLog.objects.filter(
            run=run, node_id="m", message="Passed through"
        ).count()
        self.assertEqual(visits, 1)
        self.assertTrue(
            WorkflowLog.objects.filter(run=run, node_id="m",
                                       message__contains="merged").exists()
        )
