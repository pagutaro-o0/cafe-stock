# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, session
from db import get_db, close_db, init_db as db_init_db, execute, insert_returning_id, commit


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "dev-secret-change-me"
    app.teardown_appcontext(close_db)

    # =========================
    # Helpers
    # =========================
    def get_or_create_owner_id() -> int:
    # SELECT は execute() 経由で
        owner = execute(
        "SELECT id FROM users WHERE role='owner' ORDER BY id ASC LIMIT 1"
    ).fetchone()
    if owner is not None:
        return int(owner["id"] if isinstance(owner, dict) else owner["id"])

    # INSERT は insert_returning_id() を使う（SQLite/Postgres両対応）
    owner_id = insert_returning_id(
        "INSERT INTO users (username, role) VALUES (?, ?)",
        ("吉田", "owner"),
    )
    commit()
    return int(owner_id)

     

    def ensure_demo_staff():
        for name in ("東", "大橋"):
            exists = execute(
            "SELECT 1 FROM users WHERE username = ? AND role='staff' LIMIT 1",
            (name,),
        ).fetchone()
        if not exists:
            execute(
                "INSERT INTO users (username, role) VALUES (?, ?)",
                (name, "staff"),
            )
    commit()

    def get_current_user():
        db = get_db()
        uid = session.get("user_id")

        if uid is not None:
            u = db.execute(
                "SELECT id, username, role FROM users WHERE id = ?",
                (uid,),
            ).fetchone()
            if u is not None:
                return u

        owner_id = get_or_create_owner_id()
        u = db.execute(
            "SELECT id, username, role FROM users WHERE id = ?",
            (owner_id,),
        ).fetchone()
        session["user_id"] = int(u["id"])
        return u

    def upsert_low_stock_notification(
        db,
        item_id: int,
        item_name: str,
        unit: str,
        current_qty: float,
        reorder_point: float,
        created_by: int,
    ) -> None:
        if reorder_point is None or float(reorder_point) <= 0:
            return

        if float(current_qty) < float(reorder_point):
            exists = db.execute(
                """
                SELECT id FROM notifications
                WHERE item_id = ? AND type = 'LOW_STOCK' AND is_read = 0
                LIMIT 1
                """,
                (item_id,),
            ).fetchone()
            if exists:
                return

            msg = f"在庫が少ない: {item_name}（{current_qty:g}{unit} / 目安 {reorder_point:g}{unit}）"
            db.execute(
                """
                INSERT INTO notifications (item_id, type, message, is_read, created_by, created_at)
                VALUES (?, 'LOW_STOCK', ?, 0, ?, datetime('now','localtime'))
                """,
                (item_id, msg, created_by),
            )
        else:
            db.execute(
                """
                UPDATE notifications
                SET is_read = 1, read_at = datetime('now','localtime')
                WHERE item_id = ? AND type = 'LOW_STOCK' AND is_read = 0
                """,
                (item_id,),
            )

    # =========================
    # inject globals (base.html用)
    # =========================
    @app.context_processor
    def inject_globals():
        db = get_db()
        unread_count = 0
        try:
            unread = db.execute(
                "SELECT COUNT(*) AS c FROM notifications WHERE is_read = 0"
            ).fetchone()
            unread_count = int(unread["c"]) if unread else 0
        except Exception:
            unread_count = 0

        return {
            "current_user": get_current_user(),
            "unread_notif_count": unread_count,
        }

    # =========================
    # 起動時初期化（ここだけ）
    # =========================
    with app.app_context():
        db_init_db()
        get_or_create_owner_id()
        ensure_demo_staff()

    # =========================
    # Routes
    # =========================
    @app.get("/")
    def home():
        return redirect(url_for("items_list"))

    # ---- ユーザー切替（一覧）
    @app.get("/whoami")
    def whoami():
        db = get_db()
        users = db.execute(
            """
            SELECT id, username, role
            FROM users
            WHERE COALESCE(is_active, 1) = 1
            ORDER BY (role='owner') DESC, id ASC
            """
        ).fetchall()
        return render_template("whoami.html", users=users)

    # ---- ユーザー切替（設定）
    @app.post("/whoami")
    def whoami_set():
        uid_raw = (request.form.get("user_id") or "").strip()
        try:
            uid = int(uid_raw)
        except ValueError:
            flash("ユーザーが不正です。", "error")
            return redirect(url_for("whoami"))

        db = get_db()
        u = db.execute(
            "SELECT id, username, role FROM users WHERE id = ?",
            (uid,),
        ).fetchone()

        if u is None:
            flash("ユーザーが見つかりません。", "error")
            return redirect(url_for("whoami"))

        session["user_id"] = int(u["id"])
        flash(f"現在のユーザーを「{u['username']}」に切り替えました。", "success")
        return redirect(url_for("items_list"))

    # ---- 通知一覧
    @app.get("/notifications")
    def notifications_list():
        db = get_db()
        rows = db.execute(
            """
            SELECT id, message, is_read, created_at, read_at
            FROM notifications
            ORDER BY is_read ASC, id DESC
            LIMIT 50
            """
        ).fetchall()
        return render_template("notifications_list.html", notifications=rows)

    # ---- 通知を既読
    @app.post("/notifications/<int:notif_id>/read")
    def notifications_read(notif_id: int):
        db = get_db()
        db.execute(
            """
            UPDATE notifications
            SET is_read = 1, read_at = datetime('now','localtime')
            WHERE id = ?
            """,
            (notif_id,),
        )
        db.commit()
        return redirect(url_for("notifications_list"))

    # ---- 品目一覧（有効）
    @app.get("/items")
    def items_list():
        db = get_db()
        rows = db.execute(
            """
            SELECT
              i.id, i.name, i.category, i.unit, i.reorder_point, i.track_lots,
              i.is_active,
              sl.name AS location_name,
              COALESCE(s.current_qty, 0) AS current_qty
            FROM items i
            LEFT JOIN storage_locations sl ON sl.id = i.default_location_id
            LEFT JOIN item_stock s ON s.item_id = i.id
            WHERE i.is_active = 1
            ORDER BY i.name COLLATE NOCASE ASC
            """
        ).fetchall()
        return render_template("items_list.html", items=rows)

    # ---- 品目追加フォーム（店主のみ）
    @app.get("/items/new")
    def items_new():
        current = get_current_user()
        if current["role"] != "owner":
            flash("品目の追加は店主のみできます。", "error")
            return redirect(url_for("items_list"))

        db = get_db()
        locations = db.execute(
            "SELECT id, name FROM storage_locations ORDER BY name COLLATE NOCASE ASC"
        ).fetchall()
        return render_template("items_new.html", locations=locations)

    # ---- 品目登録（POST）（店主のみ）
    @app.post("/items")
    def items_create():
        current = get_current_user()
        if current["role"] != "owner":
            flash("品目の追加は店主のみできます。", "error")
            return redirect(url_for("items_list"))

        name = (request.form.get("name") or "").strip()
        category = (request.form.get("category") or "ingredient").strip()
        unit = (request.form.get("unit") or "").strip()
        reorder_point_raw = (request.form.get("reorder_point") or "0").strip()
        default_location_id_raw = (request.form.get("default_location_id") or "").strip()
        track_lots = 1 if (request.form.get("track_lots") == "1") else 0

        if not name:
            flash("品目名を入力してください。", "error")
            return redirect(url_for("items_new"))
        if category not in ("ingredient", "consumable"):
            flash("カテゴリが不正です。", "error")
            return redirect(url_for("items_new"))
        if not unit:
            flash("単位を入力してください。", "error")
            return redirect(url_for("items_new"))

        try:
            reorder_point = float(reorder_point_raw)
            if reorder_point < 0:
                raise ValueError
        except ValueError:
            flash("目安は 0 以上の数値で入力してください。", "error")
            return redirect(url_for("items_new"))

        default_location_id = None
        if default_location_id_raw:
            try:
                default_location_id = int(default_location_id_raw)
            except ValueError:
                flash("保管場所が不正です。", "error")
                return redirect(url_for("items_new"))

        db = get_db()
        dup = db.execute("SELECT 1 FROM items WHERE name = ? LIMIT 1", (name,)).fetchone()
        if dup:
            flash("同じ品目名がすでに存在します。", "error")
            return redirect(url_for("items_new"))

        created_by = int(current["id"])
        try:
            cur = db.execute(
                """
                INSERT INTO items (
                  name, category, unit, reorder_point, track_lots, is_active,
                  default_location_id, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, datetime('now','localtime'), datetime('now','localtime'))
                """,
                (name, category, unit, reorder_point, track_lots, default_location_id, created_by),
            )
            item_id = cur.lastrowid

            db.execute(
                "INSERT INTO item_stock (item_id, current_qty, updated_at) VALUES (?, 0, datetime('now','localtime'))",
                (item_id,),
            )
            db.commit()
        except Exception as e:
            db.rollback()
            flash(f"登録に失敗しました: {e}", "error")
            return redirect(url_for("items_new"))

        flash("品目を登録しました。", "success")
        return redirect(url_for("items_list"))

    # ---- 削除した品目一覧（店主のみ）
    @app.get("/items/inactive")
    def items_inactive():
        current = get_current_user()
        if current["role"] != "owner":
            flash("確認できるのは店主のみです。", "error")
            return redirect(url_for("items_list"))

        db = get_db()
        rows = db.execute(
            """
            SELECT
              i.id, i.name, i.category, i.unit, i.reorder_point, i.track_lots,
              i.is_active,
              sl.name AS location_name,
              COALESCE(s.current_qty, 0) AS current_qty
            FROM items i
            LEFT JOIN storage_locations sl ON sl.id = i.default_location_id
            LEFT JOIN item_stock s ON s.item_id = i.id
            WHERE i.is_active = 0
            ORDER BY i.name COLLATE NOCASE ASC
            """
        ).fetchall()
        return render_template("items_inactive.html", items=rows)

    # ---- 復元（店主のみ）
    @app.post("/items/<int:item_id>/restore")
    def item_restore(item_id: int):
        current = get_current_user()
        if current["role"] != "owner":
            flash("復元は店主のみできます。", "error")
            return redirect(url_for("items_list"))

        db = get_db()
        try:
            item = db.execute(
                "SELECT id, name, is_active FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()
            if item is None:
                flash("品目が見つかりません。", "error")
                return redirect(url_for("items_inactive"))

            db.execute(
                "UPDATE items SET is_active = 1, updated_at = datetime('now','localtime') WHERE id = ?",
                (item_id,),
            )
            db.commit()
        except Exception as e:
            db.rollback()
            flash(f"復元に失敗しました: {e}", "error")
            return redirect(url_for("items_inactive"))

        flash(f"「{item['name']}」を復元しました。", "success")
        return redirect(url_for("items_inactive"))

    # ✅ これが無くて BuildError になってたやつ
    # ---- 論理削除（店主のみ）
    @app.post("/items/<int:item_id>/delete", endpoint="item_delete")
    def item_delete(item_id: int):
        current = get_current_user()
        if current["role"] != "owner":
            flash("削除は店主のみできます。", "error")
            return redirect(url_for("items_list"))

        db = get_db()
        try:
            item = db.execute(
                "SELECT id, name, is_active FROM items WHERE id = ?",
                (item_id,),
            ).fetchone()

            if item is None:
                flash("品目が見つかりません。", "error")
                return redirect(url_for("items_list"))

            if int(item["is_active"]) == 0:
                flash("この品目はすでに削除済みです。", "error")
                return redirect(url_for("items_list"))

            db.execute(
                "UPDATE items SET is_active = 0, updated_at = datetime('now','localtime') WHERE id = ?",
                (item_id,),
            )
            db.commit()
        except Exception as e:
            db.rollback()
            flash(f"削除に失敗しました: {e}", "error")
            return redirect(url_for("items_list"))

        flash(f"「{item['name']}」を削除しました。", "success")
        return redirect(url_for("items_list"))

    # ---- 履歴
    @app.get("/moves")
    def moves_list():
        db = get_db()
        rows = db.execute(
            """
            SELECT
              sm.id,
              sm.occurred_at,
              sm.move_type,
              sm.qty,
              sm.note,
              i.name AS item_name,
              i.unit AS item_unit,
              u.username AS user_name
            FROM stock_moves sm
            JOIN items i ON i.id = sm.item_id
            JOIN users u ON u.id = sm.performed_by
            ORDER BY sm.occurred_at DESC, sm.id DESC
            LIMIT 50
            """
        ).fetchall()
        return render_template("moves_list.html", moves=rows)

    # ---- 在庫増減（クイック）
    @app.post("/items/<int:item_id>/adjust")
    def item_adjust(item_id: int):
        current = get_current_user()
        performed_by = int(current["id"])

        quick = (request.form.get("quick") or "").strip()
        if quick not in ("-1", "+1", "-5", "+5"):
            flash("操作が不正です。", "error")
            return redirect(url_for("items_list"))

        qty = int(quick.replace("+", "").replace("-", ""))  # 1 or 5
        move_type = "IN" if quick.startswith("+") else "OUT"
        delta = qty if move_type == "IN" else -qty
        note = None

        db = get_db()
        try:
            item = db.execute(
                """
                SELECT id, name, unit, reorder_point
                FROM items
                WHERE id = ? AND is_active = 1
                """,
                (item_id,),
            ).fetchone()

            if item is None:
                flash("品目が見つかりません。", "error")
                return redirect(url_for("items_list"))

            row = db.execute(
                "SELECT current_qty FROM item_stock WHERE item_id = ?",
                (item_id,),
            ).fetchone()

            current_qty = float(row["current_qty"]) if row else 0.0
            new_qty = current_qty + float(delta)

            if new_qty < 0:
                flash("在庫がマイナスになるため、この操作はできません。", "error")
                return redirect(url_for("items_list"))

            # 履歴
            db.execute(
                """
                INSERT INTO stock_moves (move_type, item_id, qty, performed_by, note, occurred_at, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now','localtime'), datetime('now','localtime'))
                """,
                (move_type, item_id, qty, performed_by, note),
            )

            # 在庫更新
            if row is None:
                db.execute(
                    """
                    INSERT INTO item_stock (item_id, current_qty, updated_at)
                    VALUES (?, ?, datetime('now','localtime'))
                    """,
                    (item_id, new_qty),
                )
            else:
                db.execute(
                    """
                    UPDATE item_stock
                    SET current_qty = ?, updated_at = datetime('now','localtime')
                    WHERE item_id = ?
                    """,
                    (new_qty, item_id),
                )

            # 通知
            upsert_low_stock_notification(
                db=db,
                item_id=int(item["id"]),
                item_name=str(item["name"]),
                unit=str(item["unit"]),
                current_qty=float(new_qty),
                reorder_point=float(item["reorder_point"] or 0),
                created_by=performed_by,
            )

            db.commit()
        except Exception as e:
            db.rollback()
            flash(f"在庫更新に失敗しました: {e}", "error")
            return redirect(url_for("items_list"))

        flash("在庫を更新しました。", "success")
        return redirect(url_for("items_list"))

    return app


# ✅ gunicorn / Render 用：importされたときに app が存在するようにする
app = create_app()

# ✅ ローカル実行用
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)