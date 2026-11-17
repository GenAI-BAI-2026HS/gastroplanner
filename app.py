"""Streamlit-Oberfläche. Aufgabe A6.

    streamlit run app.py

Chat mit dem Agenten. Pro Browser-Sitzung eine thread_id; der Graph läuft mit dem
SqliteSaver (data/checkpoints.db), damit eine offene Freigabe einen Neustart übersteht.

Nichts ohne Freigabe: Die App speichert selbst nichts. Hält der Graph bei der Freigabe an
(interrupt), zeigt sie den Plan und drei Buttons. Erst «Freigeben» schickt
Command(resume={"decision": "freigeben"}); gespeichert wird dann im commit-Node.

Die Plantabelle kommt direkt aus dem State (staffing, forecast), nicht aus dem LLM-Text.
"""
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import date

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from langgraph.types import Command

load_dotenv()

import config  # noqa: E402
from agent import backends  # noqa: E402
from agent.graph import build_graph, sqlite_checkpointer  # noqa: E402
from agent.state import initial_state  # noqa: E402

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
ROLLEN = {"kueche": "Küche", "service": "Service", "abwasch": "Abwasch"}
BEISPIELE = [
    "Plane die nächste Woche",
    "Am Donnerstag kommt mittags eine Firmengruppe mit 40 Personen",
    "Reservation Firmenessen Meier AG, 25 Personen, Freitag 18 Uhr, Tel. 079 123 45 67",
    "Wie viele Gäste darf eine Servicekraft betreuen?",
]

st.set_page_config(page_title="Gastroplanner", page_icon="🍽️", layout="wide")


# --- Graph und Sitzung --------------------------------------------------------------------
@st.cache_resource
def get_graph():
    if os.getenv("CHECKPOINTER", "sqlite") == "memory":        # für Tests
        from langgraph.checkpoint.memory import InMemorySaver
        return build_graph(checkpointer=InMemorySaver())
    return build_graph(checkpointer=sqlite_checkpointer())


def neue_sitzung() -> None:
    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.verlauf = []          # [{"role", "content", "quellen", "plan"}]
    st.session_state.offen = None          # Payload des interrupt (Freigabe oder Rückfrage)


if "thread_id" not in st.session_state:
    neue_sitzung()
st.session_state.setdefault("res_ansicht", False)    # Reservationsliste im Hauptbereich offen
st.session_state.setdefault("res_vergangen", False)  # vergangene statt kommende anzeigen


def run_config() -> dict:
    return {"configurable": {"thread_id": st.session_state.thread_id},
            "run_name": "gastroplanner-app", "tags": ["app"]}


def graph_state() -> dict:
    return get_graph().get_state(run_config()).values


def ausfuehren(eingabe) -> None:
    """Startet eine neue Anfrage (str) oder setzt nach einem interrupt fort (Command)."""
    try:
        with st.spinner("Der Agent arbeitet …"):
            result = get_graph().invoke(eingabe, run_config())
    except KeyError as e:
        st.session_state.verlauf.append({"role": "assistant", "content":
            f"Einstellung fehlt: {e}. Bitte .env nach .env.example ausfüllen "
            "(MODEL, BASE_URL, API_KEY) und `python -m agent.check_gateway` ausführen."})
        st.session_state.offen = None
        return
    except Exception as e:  # noqa: BLE001 – Fehler sichtbar machen statt App-Absturz
        st.session_state.verlauf.append({"role": "assistant", "content":
            f"Technischer Fehler: {e}. Ist das LLM-Gateway erreichbar (FHNW-Netz/VPN)?"})
        st.session_state.offen = None
        return

    if "__interrupt__" in result:
        st.session_state.offen = result["__interrupt__"][0].value
        if st.session_state.offen.get("typ") == "rueckfrage":
            st.session_state.verlauf.append(
                {"role": "assistant", "content": st.session_state.offen["frage"]})
        return

    st.session_state.offen = None
    state = graph_state()
    nachricht = {"role": "assistant", "content": result["messages"][-1].content}
    if state.get("intent") == "regelfrage":
        nachricht["quellen"] = state.get("rule_sources") or []
    st.session_state.verlauf.append(nachricht)


# --- Darstellung ---------------------------------------------------------------------------
def plan_tabelle(plan: list[dict], forecast: list[dict] | None,
                 reservations: list[dict] | None = None) -> pd.DataFrame:
    spanne = {(f["date"], f["shift"]): f for f in forecast or []}
    reserviert = {(x["date"], x["shift"]): x for x in reservations or []}
    zeilen = []
    for r in plan:
        f = spanne.get((r["date"], r["shift"]))
        res = reserviert.get((r["date"], r["shift"]), {})
        d = pd.Timestamp(r["date"])
        zeilen.append({
            "Tag": f"{WOCHENTAGE[d.weekday()][:2]} {d.strftime('%d.%m.')}",
            "Schicht": r["shift"].capitalize(),
            "Gäste (Spanne)": f"{f['guests']} ({f['lower']}–{f['upper']})" if f else "–",
            "Reserviert": res.get("persons", 0),
            "Geplant für": r["guests_planned"],
            "Küche": r["kueche"], "Service": r["service"], "Abwasch": r["abwasch"],
            "Regeln": ", ".join(r.get("rule_refs", [])),
        })
    return pd.DataFrame(zeilen)


def zeige_tabelle(df: pd.DataFrame) -> None:
    """Ganze Tabelle ohne innere Scrollleiste (35 px pro Zeile + Kopf)."""
    st.dataframe(df, hide_index=True, width="stretch", height=35 * (len(df) + 1) + 3)


def archivieren(payload: dict, tabelle: pd.DataFrame) -> None:
    """Plan im Verlauf behalten, bevor die Freigabe-Ansicht verschwindet."""
    st.session_state.verlauf.append({"role": "assistant", "content": payload.get("erklaerung") or "",
                                     "plan": tabelle.to_dict("records")})


def annahmen(state: dict) -> None:
    with st.expander("Annahmen und Quellen"):
        prognose = state.get("forecast") or []
        tage = {}
        for f in prognose:
            tage.setdefault(f["date"], f.get("assumptions") or {})
        if tage:
            st.markdown("**Wetter und Kalender**")
            st.dataframe(pd.DataFrame([{
                "Datum": d,
                "Temp. max (°C)": a.get("temp_max", "–"),
                "Regen (mm)": a.get("rain_mm", "–"),
                "Feiertag": a.get("holiday_name") or ("ja" if a.get("is_holiday") else ""),
                "Brückentag": "ja" if a.get("is_bridge_day") else "",
                "Schulferien": "ja" if a.get("is_school_holiday") else "",
            } for d, a in sorted(tage.items())]), hide_index=True, width="stretch")
        if state.get("fallback_grund"):
            st.warning(f"Ersatzprognose (Wochentagsmittel): {state['fallback_grund']}")
        if state.get("events"):
            st.markdown("**Anlässe**")
            for e in state["events"]:
                st.markdown(f"- {e.get('date')} {e.get('shift')}: {e.get('persons')} Personen "
                            f"({e.get('type', 'Anlass')})")
        if state.get("reservations"):
            st.markdown("**Reservationen** (zusätzlich zur Prognose eingeplant)")
            for x in state["reservations"]:
                st.markdown(f"- {x['date']} {x['shift']}: {x['persons']} Personen")
        if state.get("corrections"):
            st.markdown("**Angewendete Korrekturen**")
            for c in state["corrections"]:
                st.markdown(f"- {korrektur_text(c)}")
        quellen(state.get("rule_sources") or [])


def quellen(hits: list[dict]) -> None:
    if hits:
        st.markdown("**Regelquellen**")
        for h in hits:
            st.caption(f"{h['source']} · {h['section']}")


def korrektur_text(c: dict) -> str:
    return (f"{WOCHENTAGE[c['weekday']]} {c['shift']}: {ROLLEN.get(c['role'], c['role'])} "
            f"{c['delta']:+d}" + (f" ({c['note']})" if c.get("note") else ""))


def freigabe(payload: dict) -> None:
    state = graph_state()
    with st.chat_message("assistant"):
        st.markdown(payload.get("erklaerung") or "")
        if payload.get("fallback_grund"):
            st.warning("Diese Woche gilt die Ersatzprognose aus dem Wochentagsmittel.")
        tabelle = plan_tabelle(payload["plan"], state.get("forecast"), state.get("reservations"))
        zeige_tabelle(tabelle)
        for k in payload.get("korrekturen_offen") or []:
            st.info(f"Wird bei Freigabe dauerhaft gespeichert: {k.get('note') or korrektur_text(k)}")
        if payload.get("hinweis"):
            st.info(payload["hinweis"])
        annahmen(state)

        st.markdown("**Freigabe:** Ohne Freigabe wird nichts gespeichert.")
        feedback = st.text_input("Was soll angepasst werden?", key="feedback",
                                 placeholder="z. B. Freitagnachmittag immer eine Servicekraft mehr "
                                             "· oder: Mittwoch kommt Firma Müller mit 30 Personen")
        a, b, c = st.columns(3)
        if a.button("Freigeben", type="primary", width="stretch"):
            archivieren(payload, tabelle)
            st.session_state.verlauf.append({"role": "user", "content": "Freigeben"})
            ausfuehren(Command(resume={"decision": "freigeben"}))
            st.rerun()
        if b.button("Anpassen", width="stretch", disabled=not feedback):
            archivieren(payload, tabelle)
            st.session_state.verlauf.append({"role": "user", "content": f"Anpassen: {feedback}"})
            ausfuehren(Command(resume={"decision": "anpassen", "feedback": feedback}))
            st.rerun()
        if c.button("Ablehnen", width="stretch"):
            archivieren(payload, tabelle)
            st.session_state.verlauf.append({"role": "user", "content": "Ablehnen"})
            ausfuehren(Command(resume={"decision": "ablehnen"}))
            st.rerun()


def reservation_bestaetigen(payload: dict) -> None:
    r = payload["reservation"]
    with st.chat_message("assistant"):
        st.markdown("Bitte prüfen Sie die Reservation. Gespeichert wird erst nach Bestätigung.")
        d = pd.Timestamp(r["datum"])
        st.table(pd.DataFrame([{
            "Name": r["name"], "Telefon": r["telefon"], "Personen": r["personen"],
            "Datum": f"{WOCHENTAGE[d.weekday()]} {d.strftime('%d.%m.%Y')}",
            "Uhrzeit": r.get("uhrzeit") or "–", "Schicht": r["schicht"].capitalize(),
            "Grund": r.get("grund") or "–",
        }]).set_index("Name"))
        if payload.get("hinweis"):
            st.caption(payload["hinweis"])
        a, b = st.columns(2)
        if a.button("Reservation speichern", type="primary", width="stretch"):
            st.session_state.verlauf.append({"role": "user", "content": "Reservation speichern"})
            ausfuehren(Command(resume={"decision": "speichern"}))
            st.rerun()
        if b.button("Verwerfen", width="stretch"):
            st.session_state.verlauf.append({"role": "user", "content": "Verwerfen"})
            ausfuehren(Command(resume={"decision": "verwerfen"}))
            st.rerun()


def aenderung_bestaetigen(payload: dict) -> None:
    """Änderung oder Stornierung einer bestehenden Reservation: vorher/nachher zeigen."""
    def zeile(titel, r):
        d = pd.Timestamp(r["datum"])
        return {"": titel, "Name": r["name"], "Telefon": r["telefon"], "Personen": r["personen"],
                "Datum": f"{WOCHENTAGE[d.weekday()][:2]} {d.strftime('%d.%m.%Y')}",
                "Uhrzeit": r.get("uhrzeit") or "–", "Schicht": r["schicht"].capitalize(),
                "Grund": r.get("grund") or "–"}

    storno = payload["aktion"] == "stornieren"
    with st.chat_message("assistant"):
        st.markdown(f"Bitte prüfen Sie die {'Stornierung' if storno else 'Änderung'} der "
                    f"Reservation Nr. {payload['nr']}. Gespeichert wird erst nach Bestätigung.")
        zeilen = [zeile("Bisher", payload["vorher"])]
        if not storno:
            zeilen.append(zeile("Neu", payload["nachher"]))
        st.table(pd.DataFrame(zeilen).set_index(""))
        a, b = st.columns(2)
        label = "Reservation stornieren" if storno else "Änderung speichern"
        if a.button(label, type="primary", width="stretch"):
            st.session_state.verlauf.append({"role": "user", "content": label})
            ausfuehren(Command(resume={"decision": "speichern"}))
            st.rerun()
        if b.button("Abbrechen", width="stretch"):
            st.session_state.verlauf.append({"role": "user", "content": "Abbrechen"})
            ausfuehren(Command(resume={"decision": "verwerfen"}))
            st.rerun()


def reservationen(kommend: bool = True) -> list[dict]:
    try:
        return backends.list_reservations(date.today(), kommend=kommend)
    except Exception:  # noqa: BLE001
        return []


def reservationen_ansicht() -> None:
    """Alle kommenden (bearbeitbar über den Chatbot) oder vergangenen Reservationen."""
    vergangen = st.session_state.res_vergangen
    kopf, umschalten, schliessen = st.columns([3, 2, 1])
    kopf.subheader("Vergangene Reservationen" if vergangen else "Kommende Reservationen")
    if umschalten.button("Kommende anzeigen" if vergangen else "Vergangene Reservationen anzeigen",
                         width="stretch", key="res_umschalten"):
        st.session_state.res_vergangen = not vergangen
        st.rerun()
    if schliessen.button("Schliessen", width="stretch", key="res_schliessen"):
        st.session_state.res_ansicht = False
        st.rerun()

    liste = reservationen(kommend=not vergangen)
    if not liste:
        st.caption("Keine vergangenen Reservationen." if vergangen else "Keine kommenden Reservationen.")
        return
    df = pd.DataFrame([{
        "Nr.": x["id"],
        "Datum": f"{WOCHENTAGE[pd.Timestamp(x['date']).weekday()][:2]} "
                 f"{pd.Timestamp(x['date']).strftime('%d.%m.%Y')}",
        "Zeit": x["time"] or x["shift"].capitalize(), "Name": x["name"],
        "Grund": x.get("occasion") or "–", "Personen": x["persons"], "Telefon": x["phone"],
    } for x in liste])
    if vergangen:
        st.dataframe(df, hide_index=True, width="stretch")
        return

    auswahl = st.dataframe(df, hide_index=True, width="stretch", on_select="rerun",
                           selection_mode="single-row", key="res_tabelle")
    zeilen = auswahl.selection.rows if auswahl else []
    if not zeilen:
        st.caption("Zeile anklicken, um die Reservation mit dem Chatbot zu bearbeiten oder zu "
                   "stornieren. Oder direkt im Chat, z. B. «Verschiebe Reservation Nr. 3 auf "
                   "Donnerstag 12 Uhr».")
        return
    x = liste[zeilen[0]]
    gesperrt = bool(st.session_state.offen and st.session_state.offen.get("typ") != "rueckfrage")
    a, b = st.columns(2)
    beschrieb = f"Nr. {x['id']} ({x['name']}, {pd.Timestamp(x['date']).strftime('%d.%m.%Y')})"
    if a.button(f"Nr. {x['id']} mit dem Chatbot bearbeiten", type="primary", width="stretch",
                disabled=gesperrt, key="res_bearbeiten"):
        chat_starten(f"Ich möchte die Reservation {beschrieb} bearbeiten.")
    if b.button(f"Nr. {x['id']} stornieren", width="stretch", disabled=gesperrt, key="res_stornieren"):
        chat_starten(f"Bitte storniere die Reservation {beschrieb}.")
    if gesperrt:
        st.caption("Bitte zuerst die offene Freigabe oder Bestätigung im Chat abschliessen.")


def chat_starten(text: str) -> None:
    st.session_state.verlauf.append({"role": "user", "content": text})
    ausfuehren(initial_state(text))
    st.rerun()


def freigegebene_plaene() -> pd.DataFrame:
    if not config.DB_PATH.exists():
        return pd.DataFrame()
    with closing(sqlite3.connect(config.DB_PATH)) as con:
        hat = con.execute("SELECT 1 FROM sqlite_master WHERE name='approved_plans'").fetchone()
        if not hat:
            return pd.DataFrame()
        return pd.read_sql(
            "SELECT plan_id AS Plan, MIN(date) AS Von, MAX(date) AS Bis, MAX(created_at) AS Freigegeben "
            "FROM approved_plans GROUP BY plan_id ORDER BY Freigegeben DESC", con)


# --- Seitenleiste ----------------------------------------------------------------------------
with st.sidebar:
    st.header("Gastroplanner")
    st.caption(f"Personalplanung {config.LOCATION_NAME} · nächste {config.HORIZON_DAYS} Tage")
    if st.button("Neues Gespräch", width="stretch"):
        neue_sitzung()
        st.rerun()

    st.subheader("Freigegebene Pläne")
    plaene = freigegebene_plaene()
    if plaene.empty:
        st.caption("Noch keine.")
    for _, plan in plaene.iterrows():
        st.caption(f"**{plan['Plan']}** · {plan['Von']} bis {plan['Bis']} · freigegeben {plan['Freigegeben'][:16].replace('T', ' ')}")

    st.subheader("Reservationen")
    kommende = reservationen(kommend=True)
    if st.button(f"Alle Reservationen anzeigen ({len(kommende)} kommende)", width="stretch",
                 key="res_oeffnen", type="primary" if st.session_state.res_ansicht else "secondary"):
        st.session_state.res_ansicht = not st.session_state.res_ansicht
        st.session_state.res_vergangen = False
        st.rerun()
    if not kommende:
        st.caption("Keine kommenden.")
    for x in kommende[:3]:
        zeit = x["time"] or x["shift"]
        grund = f" · {x['occasion']}" if x.get("occasion") else ""
        st.caption(f"Nr. {x['id']} · {x['date']} {zeit} · **{x['name']}**{grund} · {x['persons']} P.")
    if len(kommende) > 3:
        st.caption(f"… und {len(kommende) - 3} weitere")

    st.subheader("Gespeicherte Korrekturen")
    try:
        korrekturen = backends.get_corrections()
    except Exception:  # noqa: BLE001
        korrekturen = []
    if korrekturen:
        for k in korrekturen:
            st.caption(korrektur_text(k))
    else:
        st.caption("Noch keine.")

    st.divider()
    if backends.use_fixtures():
        st.warning("Beispieldaten aktiv (USE_FIXTURES=1, Woche ab 26.10.2026).")
    st.caption(f"Modell: {os.getenv('MODEL') or 'nicht gesetzt'}")


# --- Hauptbereich ----------------------------------------------------------------------------
st.title("Personalplanung")
st.caption("Der Agent plant Küche, Service und Abwasch aus der Gästeprognose plus "
           "Reservationen und erfasst Tischreservationen. Er rechnet nie selbst und "
           "übernimmt einen Plan erst nach deiner Freigabe.")

if st.session_state.res_ansicht:
    with st.container(border=True):
        reservationen_ansicht()

if not st.session_state.verlauf and not st.session_state.offen:
    st.markdown("**Beispiele**")
    for i, beispiel in enumerate(BEISPIELE):
        if st.button(beispiel, key=f"beispiel_{i}"):
            st.session_state.verlauf.append({"role": "user", "content": beispiel})
            ausfuehren(initial_state(beispiel))
            st.rerun()

for n in st.session_state.verlauf:
    with st.chat_message(n["role"]):
        st.markdown(n["content"])
        if n.get("plan"):
            zeige_tabelle(pd.DataFrame(n["plan"]))
        if n.get("quellen"):
            quellen(n["quellen"])

offen = st.session_state.offen
if offen and offen.get("typ") == "freigabe":
    freigabe(offen)
if offen and offen.get("typ") == "reservation":
    reservation_bestaetigen(offen)
if offen and offen.get("typ") == "reservation_aenderung":
    aenderung_bestaetigen(offen)

platzhalter = ("Antwort auf die Rückfrage …" if offen and offen.get("typ") == "rueckfrage"
               else "Frage oder Auftrag, z. B. «Plane die Woche ab Montag»")
if text := st.chat_input(platzhalter, disabled=bool(
        offen and offen.get("typ") in ("freigabe", "reservation", "reservation_aenderung"))):
    st.session_state.verlauf.append({"role": "user", "content": text})
    if offen and offen.get("typ") == "rueckfrage":
        ausfuehren(Command(resume=text))
    else:
        ausfuehren(initial_state(text))
    st.rerun()
