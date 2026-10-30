import requests, io, json
B = "http://127.0.0.1:8000"

def login(u, p):
    r = requests.post(f"{B}/api/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}

adm = login("admin", "admin123")
ins = login("inspector", "inspector123")
vie = login("viewer", "viewer123")

# неверный пароль
assert requests.post(f"{B}/api/login", json={"username":"admin","password":"x"}).status_code == 401

# уровни
assert requests.post(f"{B}/api/objects", json={"name":"Тест"}, headers=ins).status_code == 403
assert requests.post(f"{B}/api/objects", json={"name":"Тест"}, headers=vie).status_code == 403
assert requests.get(f"{B}/api/objects", headers=vie).status_code == 200
assert requests.patch(f"{B}/api/rooms/1", json={"status":"warranty"}, headers=vie).status_code == 403
assert requests.patch(f"{B}/api/rooms/1", json={"status":"warranty"}, headers=ins).status_code == 200
assert requests.patch(f"{B}/api/rooms/1", json={"status":"not_inspected"}, headers=ins).status_code == 200

# список объектов со статистикой
objs = requests.get(f"{B}/api/objects", headers=adm).json()
print("объекты:", [(o["name"], o["stats"]["total"]) for o in objs])
oid = objs[0]["id"]

# создание корпуса с генерацией квартир (level 3)
r = requests.post(f"{B}/api/objects/{oid}/buildings", json={"name":"Корпус Тест","address":"ул. Тестовая, 2","floors":2,"apartments_per_floor":4,"entrances":2}, headers=adm)
assert r.status_code == 201, r.text
bid = r.json()["id"]
obj = requests.get(f"{B}/api/objects/{oid}", headers=adm).json()
tb = [x for x in obj["buildings"] if x["id"] == bid][0]
assert tb["entrances"] == 2, tb
res = requests.get(f"{B}/api/buildings/{bid}/rooms", headers=adm).json()
rooms = res["rooms"] if isinstance(res, dict) else res
if isinstance(res, dict): assert res.get("entrances") == 2, res
assert len(rooms) == 8, len(rooms)
ent = {rr["number"]: rr.get("entrance") for rr in rooms}
assert ent["1"] == 1 and ent["2"] == 1 and ent["3"] == 2 and ent["4"] == 2, ent
rid = rooms[0]["id"]

# нарушение + фото (level 2)
img = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a4944415478da6360000002000100ffff03000006052aba0000000049454e44ae426082")
r = requests.post(f"{B}/api/rooms/{rid}/violations", data={"title":"Дыра в полу","status":"to_fix","text":"Фото дефекта"},
                  files={"photo": ("p.png", io.BytesIO(img), "image/png")}, headers=ins)
assert r.status_code == 201, r.text
vid = r.json()["id"]
# level 1 не может создавать нарушения
assert requests.post(f"{B}/api/rooms/{rid}/violations", data={"title":"x"}, headers=vie).status_code == 403

# событие исправления
r = requests.post(f"{B}/api/violations/{vid}/events", data={"kind":"fix","text":"Заделали"},
                  files={"photo": ("f.png", io.BytesIO(img), "image/png")}, headers=ins)
assert r.status_code == 200, r.text
eid = r.json()["id"]

# смена статуса нарушения
r = requests.patch(f"{B}/api/violations/{vid}/status", json={"status":"on_check"}, headers=ins)
assert r.status_code == 200 and r.json()["status_color"] == "#1e88e5", r.text

# акт
r = requests.post(f"{B}/api/rooms/{rid}/act", files={"file": ("akt.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")}, headers=ins)
assert r.status_code == 200, r.text
assert requests.get(f"{B}/api/rooms/{rid}/act", headers=vie).status_code == 200

room = requests.get(f"{B}/api/rooms/{rid}", headers=adm).json()
assert room["violations"][0]["events"][0]["photo_original"] == "p.png"
assert room["violations"][0]["events"][0]["photo"]  # имя на диске
assert room["acceptance_act_filename"] == "akt.pdf"
print("квартира:", room["number"], "| нарушений:", len(room["violations"]), "| событий:", len(room["violations"][0]["events"]))

# просмотр фото через static
fn = room["violations"][0]["events"][0]["photo"]
assert requests.get(f"{B}/uploads/{fn}").status_code == 200

# бекап и восстановление
bk = requests.get(f"{B}/api/backup", headers=adm)
assert bk.status_code == 200 and bk.headers["content-type"] == "application/zip"
assert requests.get(f"{B}/api/backup", headers=ins).status_code == 403
before_counts = {k: len(requests.get(f"{B}/api/objects", headers=adm).json()) for k in [0]}
r = requests.post(f"{B}/api/restore", files={"file": ("b.zip", io.BytesIO(bk.content), "application/zip")}, headers=adm)
assert r.status_code == 200, r.text
print("восстановление:", r.json()["counts"], "файлов:", r.json()["restored_files"])
# после восстановления данные на месте
objs2 = requests.get(f"{B}/api/objects", headers=adm).json()
assert len(objs2) == len(objs), (len(objs2), len(objs))
room2 = requests.get(f"{B}/api/rooms/{rid}", headers=adm).json()
assert room2["violations"][0]["events"][0]["photo"] == room["violations"][0]["events"][0]["photo"]
assert room2["violations"][0]["events"][0]["photo_original"] == "p.png"

# сотрудники
r = requests.post(f"{B}/api/employees", json={"username":"new1","password":"pp","full_name":"Новый","access_level":2}, headers=adm)
assert r.status_code == 201, r.text
nid = r.json()["id"]
r = requests.post(f"{B}/api/objects/{oid}/employees", json={"employee_id": nid}, headers=adm)
assert r.status_code == 201, r.text
aid = r.json()["id"]
o = requests.get(f"{B}/api/objects/{oid}", headers=adm).json()
assert any(e["id"] == nid for e in o["employees"])
assert requests.delete(f"{B}/api/objects/{oid}/employees/{aid}", headers=adm).status_code == 200

# index
assert requests.get(f"{B}/").status_code == 200 and "Сдача-приёмка" in requests.get(f"{B}/").text
print("\nВСЕ ТЕСТЫ ПРОЙДЕНЫ ✅")
