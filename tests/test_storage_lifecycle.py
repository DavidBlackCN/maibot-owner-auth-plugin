import asyncio
import sqlite3
import threading
import pytest
from maiidentity.host.plugin import MaiIdentityPlugin
from maiidentity.storage.database import Database, WriterLease
from maiidentity.shared.core import Denied
from .test_lifecycle import context


def test_metadata_reload_preserves_other_records_and_unknown_schema(tmp_path):
    path=tmp_path/'identity.db'
    db=Database(path,create=True)
    instance,key=db.context_state()
    db.conn.execute('CREATE TABLE records(id TEXT PRIMARY KEY, data TEXT)')
    db.conn.execute("INSERT INTO records VALUES ('existing', 'unknown result; do not replay')")
    db.close()
    db=Database(path)
    assert db.context_state()==(instance,key)
    assert tuple(db.conn.execute('SELECT * FROM records').fetchone())==('existing','unknown result; do not replay')
    db.conn.execute('PRAGMA user_version=99'); db.close()
    before=path.read_bytes()
    with pytest.raises(Denied,match='UNKNOWN_SCHEMA'): Database(path)
    assert path.read_bytes()==before
    with pytest.raises(Denied,match='STORAGE_UNAVAILABLE'): db.context_state()


@pytest.mark.asyncio
async def test_disabled_corrupt_storage_cleanup_and_lock(tmp_path):
    p=MaiIdentityPlugin(); p._set_context(context(tmp_path)[0])
    p.set_plugin_config({'plugin':{'enabled':False,'config_version':'4'}}); await p.on_load()
    assert not (tmp_path/'data').exists() and not p.ready
    data=tmp_path/'data'; data.mkdir(); path=data/'identity.db'
    path.write_bytes(b'invalid sqlite')
    p.set_plugin_config({})
    with pytest.raises(sqlite3.DatabaseError): await p.on_load()
    assert not p.ready and p.db is None and p.lease is None
    assert path.read_bytes()==b'invalid sqlite'
    lease=WriterLease(data/'writer.lock'); lease.acquire(); lease.release()


@pytest.mark.asyncio
async def test_cancelled_load_joins_storage_worker_before_releasing_lock(tmp_path,monkeypatch):
    entered,release=threading.Event(),threading.Event()
    original=Database.context_state
    def delayed(db):
        entered.set()
        assert release.wait(5)
        return original(db)
    monkeypatch.setattr(Database,'context_state',delayed)
    p=MaiIdentityPlugin(); p._set_context(context(tmp_path)[0]); p.set_plugin_config({})
    task=asyncio.create_task(p.on_load())
    try:
        assert await asyncio.to_thread(entered.wait,5)
        task.cancel(); await asyncio.sleep(0)
        lease=WriterLease(tmp_path/'data/writer.lock')
        with pytest.raises(Denied,match='WRITER_LOCKED'): lease.acquire()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
    assert p.db is None and p.lease is None and not p.ready
    lease.acquire(); lease.release()


@pytest.mark.asyncio
async def test_config_updates_clear_cached_scope_and_disable_closes_store(tmp_path):
    p=MaiIdentityPlugin(); p._set_context(context(tmp_path)[0]); p.set_plugin_config({})
    await p.on_load()
    from .test_default_install import message
    await p.receive(message=message())
    old=p.resolver
    await p.on_config_update('self',{'identity':{'route_scope':'new'}},'4')
    assert p.ready and not old.cache and not p.resolver.cache
    await p.on_config_update('self',{'plugin':{'enabled':False}},'4')
    assert not p.ready and p.db is None and p.lease is None
    assert await p.is_admin(account_id='10001')=={'is_admin':False}
