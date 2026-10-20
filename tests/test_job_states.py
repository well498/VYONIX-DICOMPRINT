"""F1-08 — máquina de estados consistente com o banco."""

import re
import unittest

from app.core.errors import InvalidStateTransition
from app.database.migrations import m0001_initial
from app.jobs.states import (IN_FLIGHT, LABELS, QUEUED, TRANSITIONS, JobState,
                             assert_transition, can_transition)


class JobStatesTest(unittest.TestCase):
    def test_enum_matches_database_check(self):
        m = re.search(r"state\s+TEXT NOT NULL CHECK \(state IN \(([^)]*)\)\)", m0001_initial.SQL)
        db_states = {s.strip().strip("'") for s in m.group(1).split(",")}
        self.assertEqual(db_states, {s.value for s in JobState})

    def test_every_state_has_label_and_transitions(self):
        self.assertEqual(set(LABELS), set(JobState))
        self.assertEqual(set(TRANSITIONS), set(JobState))

    def test_spooled_is_not_completed(self):
        self.assertNotEqual(JobState.SPOOLED, JobState.COMPLETED)
        self.assertEqual(LABELS[JobState.SPOOLED], "Enviado ao sistema de impressão")
        self.assertTrue(can_transition(JobState.SPOOLED, JobState.COMPLETED))

    def test_terminal_states_cannot_be_reprocessed(self):
        for s in (JobState.COMPLETED, JobState.CANCELLED):
            self.assertTrue(s.is_terminal)
            with self.assertRaises(InvalidStateTransition):
                assert_transition(s, JobState.VALIDATING)

    def test_spooled_cannot_be_requeued_silently(self):
        # Evita impressão duplicada: algo já enviado ao spooler não volta à fila.
        for target in (JobState.VALIDATING, JobState.PROCESSING, JobState.WAITING_PRINT):
            self.assertFalse(can_transition(JobState.SPOOLED, target))

    def test_retry_hold_release(self):
        self.assertTrue(can_transition(JobState.FAILED, JobState.VALIDATING))
        self.assertTrue(can_transition(JobState.HELD, JobState.VALIDATING))
        self.assertTrue(can_transition(JobState.RECEIVED, JobState.HELD))

    def test_all_states_reachable_from_received(self):
        seen, stack = {JobState.RECEIVED}, [JobState.RECEIVED]
        while stack:
            for nxt in TRANSITIONS[stack.pop()]:
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        self.assertEqual(seen, set(JobState))

    def test_groups(self):
        self.assertTrue(IN_FLIGHT <= QUEUED)
        self.assertNotIn(JobState.SPOOLED, QUEUED)
