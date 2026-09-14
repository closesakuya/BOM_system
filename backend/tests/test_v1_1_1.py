from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app import auth, models, schemas, services
from backend.app.database import Base


def test_unofficial_codes_are_allocated_atomically_across_sessions(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'concurrent.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    with factory() as db:
        db.add(models.User(
            username="admin", password_hash=auth.hash_password("admin123"),
            display_name="管理员", role="admin", active=True,
        ))
        db.commit()
    barrier = Barrier(2)

    def create(index: int) -> str:
        with factory() as db:
            actor = db.scalar(select(models.User).where(models.User.username == "admin"))
            assert actor
            barrier.wait()
            item = services.create_item(
                db,
                schemas.ItemCreate(
                    item_type="material",
                    code=None,
                    name=f"并发未正式物料{index}",
                    source_type="purchased",
                    is_formally_imported=False,
                    reason="并发编号测试",
                ),
                actor,
            )
            return item.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        codes = sorted(executor.map(create, (1, 2)))
    assert codes == ["99.0001.0", "99.0001.1"]
    with factory() as db:
        assert db.get(models.CodeSequence, services.UNOFFICIAL_SEQUENCE_NAME).next_value == 2
        assert db.scalar(select(models.Item).where(models.Item.code == "99.0001.0"))
        assert db.scalar(select(models.Item).where(models.Item.code == "99.0001.1"))
    engine.dispose()


def test_key_component_code_normalization_duplicate_warning_and_reserved_range(
    client: TestClient,
    headers: dict[str, str],
):
    first = client.post(
        "/api/items",
        headers=headers,
        json={
            "item_type": "material", "code": "10.9801.01", "name": "关键器件甲",
            "source_type": "purchased", "key_component_code": " f33. a ", "reason": "测试关键器件码",
        },
    )
    assert first.status_code == 201, first.text
    assert first.json()["key_component_code"] == "F33.A"
    duplicate = client.get(
        "/api/items/key-component-code-availability",
        headers=headers,
        params={"value": "f33.a"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["valid"] is True
    assert [row["id"] for row in duplicate.json()["duplicate_items"]] == [first.json()["id"]]

    second = client.post(
        "/api/items",
        headers=headers,
        json={
            "item_type": "material", "code": "10.9802.01", "name": "关键器件乙",
            "source_type": "purchased", "key_component_code": "F33.A", "reason": "允许关键器件码重复",
        },
    )
    assert second.status_code == 201, second.text
    invalid = client.post(
        "/api/items",
        headers=headers,
        json={
            "item_type": "material", "code": "10.9803.01", "name": "关键器件丙",
            "source_type": "purchased", "key_component_code": "INVALID", "reason": "拒绝格式错误",
        },
    )
    assert invalid.status_code == 422
    reserved = client.post(
        "/api/items",
        headers=headers,
        json={
            "item_type": "material", "code": "99.1234.5", "name": "错误占号",
            "source_type": "purchased", "reason": "拒绝正式占用专属号段",
        },
    )
    assert reserved.status_code == 422
