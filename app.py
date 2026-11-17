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
import uuid
from datetime import date, datetime

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from langgraph.types import Command

load_dotenv()

import config  # noqa: E402
from agent import backends  # noqa: E402
from agent.graph import build_graph, sqlite_checkpointer  # noqa: E402
from agent.nodes.reservation import betrifft_planung, plaene_neu_freigeben  # noqa: E402
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
    st.session_state.res_ansicht = False   # zurück zur Startseite mit Chat und Beispielen
    st.session_state.plan_ansicht = False
    st.session_state.res_bearbeiten = None


if "thread_id" not in st.session_state:
    neue_sitzung()
st.session_state.setdefault("res_ansicht", False)    # Reservationsliste im Hauptbereich offen
st.session_state.setdefault("res_vergangen", False)  # vergangene statt kommende anzeigen
st.session_state.setdefault("res_bearbeiten", None)  # ID der Reservation im Bearbeitungsformular


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


RES_SPALTEN = [2, 1, 1, 2, 2, 2, 1]


def datum_text(iso: str) -> str:
    d = pd.Timestamp(iso)
    return f"{WOCHENTAGE[d.weekday()][:2]} {d.strftime('%d.%m.%Y')}"


def reservationen_ansicht() -> None:
    """Alle kommenden (pro Zeile bearbeitbar) oder vergangenen Reservationen."""
    vergangen = st.session_state.res_vergangen
    kopf, hinzufuegen, umschalten, schliessen = st.columns([3, 2, 2, 1])
    kopf.subheader("Vergangene Reservationen" if vergangen else "Kommende Reservationen")
    if hinzufuegen.button("Reservation hinzufügen", type="primary", width="stretch",
                          key="res_hinzufuegen"):
        neue_sitzung()
        st.rerun()
    if umschalten.button("Kommende anzeigen" if vergangen else "Vergangene Reservationen anzeigen",
                         width="stretch", key="res_umschalten"):
        st.session_state.res_vergangen = not vergangen
        st.session_state.res_bearbeiten = None
        st.rerun()
    if schliessen.button("Schliessen", width="stretch", key="res_schliessen"):
        st.session_state.res_ansicht = False
        st.session_state.res_bearbeiten = None
        st.rerun()

    if meldung := st.session_state.pop("res_meldung", None):
        st.success(meldung)

    liste = reservationen(kommend=not vergangen)
    if not liste:
        st.caption("Keine vergangenen Reservationen." if vergangen else "Keine kommenden Reservationen.")
        return
    if vergangen:
        st.dataframe(pd.DataFrame([{
            "Datum": datum_text(x["date"]), "Uhrzeit": x["time"] or x["shift"].capitalize(),
            "Personen": x["persons"], "Anlass": x.get("occasion") or "–",
            "Name": x["name"], "Tel. Nr.": x["phone"],
        } for x in liste]), hide_index=True, width="stretch")
        return

    for spalte, titel in zip(st.columns(RES_SPALTEN),
                             ["Datum", "Uhrzeit", "Personen", "Anlass", "Name", "Tel. Nr.", ""]):
        spalte.markdown(f"**{titel}**")
    for x in liste:
        c = st.columns(RES_SPALTEN, vertical_alignment="center")
        c[0].write(datum_text(x["date"]))
        c[1].write(x["time"] or x["shift"].capitalize())
        c[2].write(str(x["persons"]))
        c[3].write(x.get("occasion") or "–")
        c[4].write(x["name"])
        c[5].write(x["phone"])
        offen = st.session_state.res_bearbeiten == x["id"]
        if c[6].button("✏️", key=f"res_edit_{x['id']}", help="Reservation bearbeiten",
                       type="primary" if offen else "secondary"):
            st.session_state.res_bearbeiten = None if offen else x["id"]
            st.rerun()
        if offen:
            reservation_formular(x)


def reservation_formular(x: dict) -> None:
    """Formular zum Bearbeiten oder Stornieren einer Reservation. Prüft wie der Agent."""
    from tools.reservations import pruefen, schicht_aus_uhrzeit, telefon_normalisieren

    rid = x["id"]
    with st.form(f"res_form_{rid}", border=True):
        st.markdown(f"**Reservation Nr. {rid} bearbeiten**")
        a, b, c = st.columns(3)
        datum = a.date_input("Datum", value=date.fromisoformat(x["date"]), format="DD.MM.YYYY",
                             key=f"res_datum_{rid}")
        zeit_alt = datetime.strptime(x["time"], "%H:%M").time() if x["time"] else None
        zeit = b.time_input("Uhrzeit", value=zeit_alt, step=900, key=f"res_zeit_{rid}")
        personen = c.number_input("Anzahl Personen", min_value=config.RESERVATION_MIN_PERSONEN,
                                  max_value=config.CAPACITY_PER_SHIFT, step=1,
                                  value=int(x["persons"]), key=f"res_personen_{rid}")
        d, e, f = st.columns(3)
        anlass = d.text_input("Anlass", value=x.get("occasion") or "", key=f"res_anlass_{rid}")
        name = e.text_input("Name", value=x["name"], key=f"res_name_{rid}")
        telefon = f.text_input("Tel. Nr.", value=x["phone"], key=f"res_telefon_{rid}")
        storno = st.checkbox("Reservation stornieren", key=f"res_storno_{rid}")
        s1, s2 = st.columns(2)
        speichern = s1.form_submit_button("Speichern", type="primary", width="stretch")
        abbrechen = s2.form_submit_button("Abbrechen", width="stretch")

    if abbrechen:
        st.session_state.res_bearbeiten = None
        st.rerun()
    if not speichern:
        return
    alt = {"datum": x["date"], "schicht": x["shift"], "personen": int(x["persons"])}
    if storno:
        backends.delete_reservation(rid)
        st.session_state.res_bearbeiten = None
        st.session_state.res_meldung = f"Reservation Nr. {rid} ({x['name']}) storniert." +             plaene_neu_freigeben(betrifft_planung(alt, None), f"Reservation Nr. {rid} storniert")
        st.rerun()

    uhrzeit = zeit.strftime("%H:%M") if zeit else None
    schicht = schicht_aus_uhrzeit(uhrzeit) if uhrzeit else x["shift"]
    fehler = pruefen({"datum": datum.isoformat(), "uhrzeit": uhrzeit, "telefon": telefon,
                      "personen": int(personen), "schicht": schicht}, date.today())
    if not name.strip():
        fehler["name"] = "Name fehlt."
    if fehler:
        for text in fehler.values():
            st.error(text)
        return
    try:
        backends.update_reservation(rid, name.strip(), telefon_normalisieren(telefon), int(personen),
                                    datum.isoformat(), schicht, uhrzeit, anlass)
    except ValueError as err:
        st.error(str(err))
        return
    neu = {"datum": datum.isoformat(), "schicht": schicht, "personen": int(personen)}
    st.session_state.res_bearbeiten = None
    st.session_state.res_meldung = f"Reservation Nr. {rid} ({name.strip()}) gespeichert." +         plaene_neu_freigeben(betrifft_planung(alt, neu), f"Reservation Nr. {rid} geändert")
    st.rerun()


def chat_starten(text: str) -> None:
    st.session_state.verlauf.append({"role": "user", "content": text})
    ausfuehren(initial_state(text))
    st.rerun()


def freigegebene_plaene() -> list[dict]:
    try:
        return backends.list_approved_plans()
    except Exception:  # noqa: BLE001
        return []


def woche_text(p: dict) -> str:
    von, bis = pd.Timestamp(p["von"]), pd.Timestamp(p["bis"])
    return f"KW {von.isocalendar().week} · {von.strftime('%d.%m.')} – {bis.strftime('%d.%m.%Y')}"


def reservierte_gaeste(von: str, bis: str) -> dict[tuple[str, str], int]:
    """Aktuell reservierte Personen pro (Tag, Schicht) im Zeitraum [von, bis]."""
    try:
        tage = (pd.Timestamp(bis) - pd.Timestamp(von)).days + 1
        liste = backends.get_reservations(von, tage)
    except Exception:  # noqa: BLE001
        return {}
    summe: dict[tuple[str, str], int] = {}
    for x in liste:
        summe[(x["date"], x["shift"])] = summe.get((x["date"], x["shift"]), 0) + int(x["persons"])
    return summe


def plaene_ansicht() -> None:
    """Alle freigegebenen Wochen; aufklappen zeigt den ganzen Plan."""
    kopf, neu, schliessen = st.columns([5, 2, 1])
    kopf.subheader("Freigegebene Wochen")
    if neu.button("Neuen Plan erstellen", type="primary", width="stretch", key="plan_neu"):
        neue_sitzung()
        st.rerun()
    if schliessen.button("Schliessen", width="stretch", key="plan_schliessen"):
        st.session_state.plan_ansicht = False
        st.rerun()

    plaene = freigegebene_plaene()
    if not plaene:
        st.caption("Noch keine freigegebenen Pläne.")
        return
    for p in plaene:
        if p.get("neu_freigeben"):
            if st.button(f"Plan erneut freigeben: {woche_text(p)} (Plan-ID {p['plan_id']}). "
                         f"Grund: {p.get('grund') or 'Reservationen geändert'}. "
                         "Hier klicken, um den Plan neu zu erstellen.",
                         icon="⚠️", type="primary", width="stretch", key=f"plan_neu_{p['plan_id']}"):
                neue_sitzung()
                chat_starten(f"Plane die Woche ab {pd.Timestamp(p['von']).strftime('%d.%m.%Y')}")
    st.caption("Woche anklicken, um den ganzen Plan zu sehen. Freigegebene Wochen werden nicht "
               "neu geplant, ausser sie müssen erneut freigegeben werden.")
    for p in plaene:
        freigegeben = p["created_at"][:16].replace("T", " ")
        status = "  ·  ⚠️ muss neu freigegeben werden" if p.get("neu_freigeben") else ""
        total = sum(reservierte_gaeste(p["von"], p["bis"]).values())
        with st.expander(f"{woche_text(p)}  ·  {total} reservierte Gäste  ·  freigegeben "
                         f"{freigegeben}  ·  Plan-ID {p['plan_id']}{status}"):
            if p.get("neu_freigeben"):
                st.warning(f"Muss neu freigegeben werden. Grund: {p.get('grund') or 'unbekannt'}. "
                           f"Dieser Plan gilt bis zur neuen Freigabe; erstelle dafür einen neuen "
                           f"Plan für die Woche ab {pd.Timestamp(p['von']).strftime('%d.%m.')}.")
            zeilen = backends.get_approved_plan(p["plan_id"])
            reserviert = reservierte_gaeste(p["von"], p["bis"])
            df = pd.DataFrame([{
                "Tag": f"{WOCHENTAGE[pd.Timestamp(r['date']).weekday()][:2]} "
                       f"{pd.Timestamp(r['date']).strftime('%d.%m.')}",
                "Schicht": r["shift"].capitalize(),
                "Reserviert": reserviert.get((r["date"], r["shift"]), 0),
                "Geplant für": r["guests_planned"],
                "Küche": r["kueche"], "Service": r["service"], "Abwasch": r["abwasch"],
            } for r in zeilen])
            zeige_tabelle(df)


# --- Seitenleiste ----------------------------------------------------------------------------
with st.sidebar:
    st.header("Gastroplanner")
    st.caption(f"Personalplanung {config.LOCATION_NAME} · nächste {config.HORIZON_DAYS} Tage")
    if st.button("Neues Gespräch", width="stretch"):
        neue_sitzung()
        st.rerun()

    st.subheader("Freigegebene Pläne")
    plaene = freigegebene_plaene()
    if st.button(f"Freigegebene Pläne anzeigen ({len(plaene)})", width="stretch", key="plan_oeffnen",
                 type="primary" if st.session_state.plan_ansicht else "secondary"):
        st.session_state.plan_ansicht = not st.session_state.plan_ansicht
        st.session_state.res_ansicht = False
        st.rerun()
    if not plaene:
        st.caption("Noch keine.")
    for p in plaene[:3]:
        st.caption(f"{woche_text(p)} · Plan-ID {p['plan_id']}"
                   + (" · ⚠️ neu freigeben" if p.get("neu_freigeben") else ""))
    offen_neu = [p for p in plaene if p.get("neu_freigeben")]
    if offen_neu:
        st.warning(f"{len(offen_neu)} Plan/Pläne müssen wegen neuer Reservationen neu "
                   "freigegeben werden.")
    if len(plaene) > 3:
        st.caption(f"… und {len(plaene) - 3} weitere")

    st.subheader("Reservationen")
    kommende = reservationen(kommend=True)
    if st.button(f"Alle Reservationen anzeigen ({len(kommende)} kommende)", width="stretch",
                 key="res_oeffnen", type="primary" if st.session_state.res_ansicht else "secondary"):
        st.session_state.res_ansicht = not st.session_state.res_ansicht
        st.session_state.plan_ansicht = False
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
if st.session_state.res_ansicht:           # Reservationsliste ersetzt Chat und Beispiele
    st.title("Reservationen")
    reservationen_ansicht()
    st.stop()
if st.session_state.plan_ansicht:          # Planliste ersetzt Chat und Beispiele
    st.title("Freigegebene Pläne")
    plaene_ansicht()
    st.stop()

st.title("Personalplanung")
st.caption("Der Agent plant Küche, Service und Abwasch aus der Gästeprognose plus "
           "Reservationen und erfasst Tischreservationen. Er rechnet nie selbst und "
           "übernimmt einen Plan erst nach deiner Freigabe.")

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
