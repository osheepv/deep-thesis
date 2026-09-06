# -*- coding: utf-8 -*-
"""M4 状态存储 —— Repository 接口与实现。

提供 FSM 状态的读写抽象：
    - FsmRepository: 领域级仓储接口（纯 Python，可注入内存实现供单测）。
    - InMemoryFsmRepository: 内存实现（单测 / 快速原型）。
    - SqlAlchemyFsmRepository: SQLAlchemy 2.0 实现（生产，落 PostgreSQL）。

事务边界约定（系统设计 §3.2.M1）：
    - FSM 状态 + 验收 Gate 必须同一 DB 事务 → 统一由 persist_transition 提交；
    - 主产物同步，附属产物异步（readme 相关处预留注释）。
"""
from __future__ import annotations

from typing import Optional, Protocol
from copy import deepcopy
from jobs.runtime import job_write_fence

from fsm.state.models import AcceptanceGate, FsmState


class FsmRepository(Protocol):
    """FSM 状态仓储接口。"""

    def get_by_task_id(self, task_id: str) -> Optional[FsmState]:
        """按任务 ID 读取 FSM 状态，不存在返回 None。"""
        ...

    def save(self, state: FsmState) -> None:
        """保存（insert or update）FSM 状态。"""
        ...

    def record_gate(self, gate: AcceptanceGate) -> None:
        """记录一次验收看门结果。"""
        ...

    def persist_transition(self, state: FsmState, gate: Optional[AcceptanceGate] = None) -> None:
        """原子提交：FSM 状态 + 验收 Gate 在同一事务内落库。"""
        ...

    def list_task_ids(self) -> list[str]:
        """列出全部 FSM 任务 ID，供启动对账使用。"""
        ...


# ============================================================
# 内存实现（单测/原型）
# ============================================================
class InMemoryFsmRepository:
    """内存版仓储。"""

    def __init__(self) -> None:
        self._states: dict[str, FsmState] = {}
        self._gates: list[AcceptanceGate] = []

    def get_by_task_id(self, task_id: str) -> Optional[FsmState]:
        return deepcopy(self._states.get(task_id))

    def save(self, state: FsmState) -> None:
        with job_write_fence(state.task_id):
            self._states[state.task_id] = deepcopy(state)

    def record_gate(self, gate: AcceptanceGate) -> None:
        with job_write_fence(gate.task_id):
            self._gates.append(deepcopy(gate))

    def persist_transition(self, state: FsmState, gate: Optional[AcceptanceGate] = None) -> None:
        # 内存实现：原子性天然成立（单进程），先写状态再记看门。
        with job_write_fence(state.task_id):
            self._states[state.task_id] = deepcopy(state)
            if gate is not None:
                self._gates.append(deepcopy(gate))

    def gates(self, task_id: Optional[str] = None) -> list[AcceptanceGate]:
        """取看门记录（测试辅助）。"""
        if task_id is None:
            return list(self._gates)
        return [g for g in self._gates if g.task_id == task_id]

    def list_task_ids(self) -> list[str]:
        return sorted(self._states)

    def delete(self, task_id: str) -> None:
        """删除任务状态与看门。"""
        with job_write_fence(task_id):
            self._states.pop(task_id, None)
            self._gates = [g for g in self._gates if g.task_id != task_id]


# ============================================================
# SQLAlchemy 实现（生产）
# ============================================================
class SqlAlchemyFsmRepository:
    """基于 SQLAlchemy 2.0 的仓储实现（落 PostgreSQL）。

    目标：单次业务调用内原子提交 FsmState + AcceptanceGate（persist_transition）。
    附属产物（aux_artifacts）仅写入状态本体，不作为本事务的阻塞点。
    """

    def __init__(self, session_factory) -> None:
        # session_factory: 可调用，每次调用返回一个新的 Session 实例（通常为 sessionmaker）。
        self._session_factory = session_factory

    def _new_session(self):
        """创建一个新的 Session（不挂在实例上，避免与业务字段冲突）。"""
        return self._session_factory()

    def _upsert_state(self, session, state: FsmState) -> "FsmStateModel":
        from fsm.state.orm import FsmStateModel
        from sqlalchemy import select

        row = session.execute(
            select(FsmStateModel).where(FsmStateModel.task_id == state.task_id)
        ).scalar_one_or_none()

        stack_json = [e.to_dict() for e in state.rollback_stack] if state.rollback_stack else []
        phase = state.phase_state.value if hasattr(state.phase_state, "value") else state.phase_state
        degree = state.degree.value if hasattr(state.degree, "value") else state.degree

        if row is None:
            row = FsmStateModel(
                task_id=state.task_id,
                current_ring_no=state.current_ring_no,
                degree=degree,
                prev_ring_no=state.prev_ring_no,
                rollback_stack=stack_json,
                phase_state=phase,
                title=state.title or "",
                subject_field=state.subject_field or "",
                template_id=state.template_id or "",
                hitl_confirmed=state.hitl_confirmed,
                artifacts=state.artifacts or {},
                aux_artifacts=state.aux_artifacts or {},
                biz_req_no=state.biz_req_no or "",
            )
            session.add(row)
        else:
            row.current_ring_no = state.current_ring_no
            row.degree = degree
            row.prev_ring_no = state.prev_ring_no
            row.rollback_stack = stack_json
            row.phase_state = phase
            row.title = state.title or ""
            row.subject_field = state.subject_field or ""
            row.template_id = state.template_id or ""
            row.hitl_confirmed = state.hitl_confirmed
            row.artifacts = state.artifacts or {}
            row.aux_artifacts = state.aux_artifacts or {}
            row.biz_req_no = state.biz_req_no or ""
        return row

    def get_by_task_id(self, task_id: str) -> Optional[FsmState]:
        from fsm.state.orm import FsmStateModel, fsm_state_to_domain
        from sqlalchemy import select

        with self._new_session() as session:
            row = session.execute(
                select(FsmStateModel).where(FsmStateModel.task_id == task_id)
            ).scalar_one_or_none()
            return fsm_state_to_domain(row) if row is not None else None

    def list_task_ids(self) -> list[str]:
        from fsm.state.orm import FsmStateModel
        from sqlalchemy import select

        with self._new_session() as session:
            rows = session.execute(
                select(FsmStateModel.task_id).order_by(FsmStateModel.task_id)
            ).scalars()
            return [str(task_id) for task_id in rows]

    def save(self, state: FsmState) -> None:
        with job_write_fence(state.task_id), self._new_session() as session:
            self._upsert_state(session, state)
            session.commit()

    def record_gate(self, gate: AcceptanceGate) -> None:
        from fsm.state.orm import AcceptanceGateModel

        with job_write_fence(gate.task_id), self._new_session() as session:
            session.add(
                AcceptanceGateModel(
                    task_id=gate.task_id,
                    ring_no=gate.ring_no,
                    accepted=gate.accepted,
                    reject_reason=gate.reject_reason,
                    gate_rule=gate.gate_rule,
                )
            )
            session.commit()

    def delete(self, task_id: str) -> None:
        """删除任务状态与看门（级联）。"""
        from fsm.state.orm import AcceptanceGateModel, FsmStateModel
        from sqlalchemy import delete as _del

        with job_write_fence(task_id), self._new_session() as session:
            session.execute(_del(FsmStateModel).where(FsmStateModel.task_id == task_id))
            session.execute(_del(AcceptanceGateModel).where(AcceptanceGateModel.task_id == task_id))
            session.commit()

    def persist_transition(self, state: FsmState, gate: Optional[AcceptanceGate] = None) -> None:
        """原子提交：在同一 session 内完成 FSM 状态 upsert + 看门记录。

        这是 FsmOrchestrator 推进/回退时使用的**唯一**落库入口，
        保证「FSM 状态 + 验收 Gate」要么一起成功、要么一起失败（同一事务）。
        """
        from fsm.state.orm import AcceptanceGateModel

        with job_write_fence(state.task_id), self._new_session() as session:
            self._upsert_state(session, state)
            if gate is not None:
                session.add(
                    AcceptanceGateModel(
                        task_id=gate.task_id,
                        ring_no=gate.ring_no,
                        accepted=gate.accepted,
                        reject_reason=gate.reject_reason,
                        gate_rule=gate.gate_rule,
                    )
                )
            session.commit()
