
import os, json, random, sqlite3
from datetime import datetime, date, timedelta
import streamlit as st
import pandas as pd
import plotly.express as px
from dotenv import load_dotenv

load_dotenv()
st.set_page_config(page_title="RecallIQ", page_icon="🧠", layout="wide")

DB="recalliq.db"
KEY=os.getenv("GEMINI_API_KEY","").strip()
PRIMARY=os.getenv("GEMINI_MODEL","gemini-3.5-flash-lite").strip()
MODELS=list(dict.fromkeys([PRIMARY,"gemini-2.5-flash-lite","gemini-2.5-flash"]))
client=None
if KEY:
    try:
        from google import genai
        client=genai.Client(api_key=KEY)
    except Exception:
        client=None

st.markdown("""
<style>
.stApp{background:#0B0F19;color:#F8FAFC}
section[data-testid="stSidebar"]{background:#080C14;border-right:1px solid #202938}
.block-container{max-width:1400px;padding-top:2rem}
h1,h2,h3{color:#F8FAFC!important}
p,label,span{color:#CBD5E1}
.stButton>button{background:#7C3AED;color:white;border:0;border-radius:10px;font-weight:600}
.stButton>button:hover{background:#6D28D9;color:white}
.hero{background:linear-gradient(135deg,#121826,#17112B);border:1px solid #2A2340;border-radius:20px;padding:30px;margin-bottom:25px}
.card,.metric{background:#121826;border:1px solid #222C3D;border-radius:15px;padding:18px;margin:8px 0}
.metric{min-height:120px}.muted{color:#94A3B8}.value{font-size:30px;font-weight:800;color:#F8FAFC}
.title{color:#22D3EE;font-size:18px;font-weight:700}
hr{border-color:#202938}
</style>
""",unsafe_allow_html=True)

def con():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def init():
    c=con()
    c.execute("""CREATE TABLE IF NOT EXISTS topics(
    id INTEGER PRIMARY KEY AUTOINCREMENT,subject TEXT NOT NULL,topic TEXT NOT NULL,
    difficulty TEXT NOT NULL DEFAULT 'Medium',mastery REAL NOT NULL DEFAULT 0,
    last_revision TEXT,revision_count INTEGER NOT NULL DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS quiz_results(
    id INTEGER PRIMARY KEY AUTOINCREMENT,subject TEXT NOT NULL,topic TEXT NOT NULL,
    score INTEGER,total INTEGER,percentage REAL,created_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS exams(
    id INTEGER PRIMARY KEY AUTOINCREMENT,exam_name TEXT NOT NULL,exam_date TEXT NOT NULL)""")
    c.commit(); c.close()
init()

def rows(q,p=()):
    c=con(); r=[dict(x) for x in c.execute(q,p).fetchall()]; c.close(); return r
def run(q,p=()):
    c=con(); c.execute(q,p); c.commit(); c.close()

def topics(): return rows("SELECT * FROM topics ORDER BY subject,topic")
def quizzes(): return rows("SELECT * FROM quiz_results ORDER BY created_at DESC")
def exams(): return rows("SELECT * FROM exams ORDER BY exam_date")

# ---------------- SAFE AI ----------------
def ai(prompt):
    if not client: return None
    for model in MODELS:
        for _ in range(2):
            try:
                r=client.models.generate_content(model=model,contents=prompt)
                if getattr(r,"text",None): return r.text.strip()
            except Exception:
                # 503 / 429 / quota / invalid model / network:
                # deliberately hidden from the user.
                continue
    return None

def local_guide(t):
    l=t.lower()
    presets={
    "python":(["Python is a high-level language.","Indentation defines code blocks.",
               "It supports object-oriented programming.","It has many useful libraries."],
              "Python = Simple Syntax + Powerful Libraries",
              "Python is used in automation, data analysis, AI and web development."),
    "machine learning":(["ML learns patterns from data.","Supervised learning uses labelled data.",
                         "Unsupervised learning uses unlabelled data.","Models are evaluated with metrics."],
                        "Learn → Train → Test → Predict",
                        "Spam detection is a common ML application."),
    "iot":(["IoT connects physical devices.","Sensors collect data.","Networks transfer data.",
            "Cloud or edge systems process data."],"Sense → Send → Process → Act",
           "A smart temperature sensor can send data to a dashboard.")
    }
    k=next((k for k in presets if k in l),None)
    if k: p,m,e=presets[k]
    else:
        p=[f"Understand the definition of {t}.",f"Learn the main concepts of {t}.",
           f"Connect {t} with an example.","Use active recall while revising."]
        m=f"Create a short acronym from the main concepts of {t}."
        e=f"Think of one real-life application of {t}."
    return {"points":p,"trick":m,"example":e,
            "simple":f"{t} is easier when you understand the basic idea and connect concepts to examples.",
            "revision":f"Recall the definition, three key points and one example of {t}.",
            "questions":[f"What is {t}?",f"What are the main concepts of {t}?",
                         f"Give one real-life example of {t}."]}

def local_quiz(t,n):
    bank=[
    {"question":f"What is a good first step when learning {t}?","options":["Understand the basics","Skip definitions","Avoid examples","Never practise"],"answer":0,"explanation":"A strong foundation helps later concepts."},
    {"question":f"Which technique improves recall of {t}?","options":["Active recall","Only rereading","Ignoring mistakes","No practice"],"answer":0,"explanation":"Active recall strengthens retrieval."},
    {"question":f"What should you do after getting a {t} question wrong?","options":["Understand the mistake","Ignore it","Stop learning","Delete the topic"],"answer":0,"explanation":"Mistakes provide useful learning signals."},
    {"question":f"What helps you understand {t}?","options":["A real-life example","Skipping practice","Avoiding questions","Memorising blindly"],"answer":0,"explanation":"Examples connect theory to practice."},
    {"question":f"What is a useful revision strategy for {t}?","options":["Short repeated recall","One huge session only","Never retest","Avoid weak areas"],"answer":0,"explanation":"Repeated retrieval supports retention."}]
    random.shuffle(bank); return bank[:n]

def make_guide(t):
    text=ai(f"""You are RecallIQ, a study coach. Create a concise guide for "{t}".
Use headings KEY POINTS, MEMORY TRICK, SIMPLE EXPLANATION, REAL-LIFE EXAMPLE,
1-MINUTE REVISION, ACTIVE RECALL, FLASHCARDS and TEACH-BACK.
Keep it simple and exam-friendly.""")
    return text if text else local_guide(t)

def make_quiz(t,d,n):
    text=ai(f"""Create {n} MCQs about "{t}" at {d} difficulty.
Return ONLY JSON. Each item: question, options (4 strings), answer (0-3), explanation.""")
    if text:
        try:
            data=json.loads(text.replace("```json","").replace("```","").strip())
            good=[x for x in data if isinstance(x,dict) and len(x.get("options",[]))==4
                  and str(x.get("answer","")).isdigit() and 0<=int(x["answer"])<=3]
            if good: return good[:n],True
        except Exception: pass
    return local_quiz(t,n),False

# ---------------- PAGES ----------------
def dashboard():
    ts=topics(); qs=quizzes()
    avg=sum(float(x["mastery"]) for x in ts)/len(ts) if ts else 0
    weak=[x for x in ts if float(x["mastery"])<50]
    st.markdown('<div class="hero"><div style="font-size:42px;font-weight:800">🧠 RecallIQ</div>'
                '<div style="font-size:19px;color:#94A3B8">Know What to Learn. '
                '<span style="color:#22D3EE;font-weight:700">Know When to Recall.</span></div>'
                '<div style="margin-top:12px;color:#64748B">AI-powered personalized learning and revision assistant.</div></div>',
                unsafe_allow_html=True)
    cols=st.columns(4)
    vals=[("Total Topics",len(ts),"Topics you're learning"),
          ("Average Mastery",f"{avg:.0f}%","Overall understanding"),
          ("Weak Topics",len(weak),"Need more revision"),
          ("Quizzes Taken",len(qs),"Practice sessions")]
    for c,(a,b,d) in zip(cols,vals):
        with c: st.markdown(f'<div class="metric"><div class="muted">{a}</div><div class="value">{b}</div><div class="muted">{d}</div></div>',unsafe_allow_html=True)
    st.subheader("✨ Study Recommendation")
    if weak:
        w=min(weak,key=lambda x:float(x["mastery"]))
        st.markdown(f'<div class="card"><div class="title">🎯 Focus on {w["topic"]}</div>Current mastery: <b>{float(w["mastery"]):.0f}%</b>. Review for 15–20 minutes and take a short quiz.</div>',unsafe_allow_html=True)
    else: st.success("🎉 Add topics to start your personalized learning journey." if not ts else "🎉 No topic is currently below 50% mastery.")
    if ts:
        d=pd.DataFrame(ts)[["subject","topic","difficulty","mastery","revision_count"]]
        d.columns=["Subject","Topic","Difficulty","Mastery %","Revisions"]
        st.dataframe(d,use_container_width=True,hide_index=True)

def learning():
    st.title("📚 My Learning"); st.write("Add and manage your subjects and topics.")
    with st.form("add"):
        a,b,c=st.columns([1,1,.7])
        s=a.text_input("Subject",placeholder="Machine Learning")
        t=b.text_input("Topic",placeholder="KNN")
        d=c.selectbox("Difficulty",["Easy","Medium","Hard"])
        ok=st.form_submit_button("➕ Add Topic",use_container_width=True)
    if ok:
        if not s.strip() or not t.strip(): st.warning("Please enter subject and topic.")
        else:
            run("INSERT INTO topics(subject,topic,difficulty) VALUES(?,?,?)",(s.strip(),t.strip(),d))
            st.success("Topic added!"); st.rerun()
    st.markdown("---")
    for x in topics():
        with st.expander(f'{x["subject"]} → {x["topic"]}'):
            a,b=st.columns(2)
            ns=a.text_input("Subject",x["subject"],key=f"s{x['id']}")
            nt=a.text_input("Topic",x["topic"],key=f"t{x['id']}")
            nd=a.selectbox("Difficulty",["Easy","Medium","Hard"],index=["Easy","Medium","Hard"].index(x["difficulty"]),key=f"d{x['id']}")
            nm=b.slider("Mastery",0,100,int(x["mastery"]),key=f"m{x['id']}")
            if x["last_revision"]: b.caption("Last revision: "+x["last_revision"])
            u,v=st.columns(2)
            if u.button("💾 Save",key=f"u{x['id']}",use_container_width=True):
                run("UPDATE topics SET subject=?,topic=?,difficulty=?,mastery=? WHERE id=?",(ns,nt,nd,nm,x["id"])); st.success("Updated!"); st.rerun()
            if v.button("🗑️ Delete",key=f"z{x['id']}",use_container_width=True):
                run("DELETE FROM topics WHERE id=?",(x["id"],)); st.success("Deleted!"); st.rerun()

def quiz():
    st.title("🧠 AI Quiz"); st.write("Test your understanding.")
    ts=topics()
    if not ts: st.info("Add a topic first."); return
    labels=[f'{x["subject"]} → {x["topic"]}' for x in ts]
    ch=st.selectbox("Choose Topic",labels); x=ts[labels.index(ch)]
    d=st.selectbox("Difficulty",["Easy","Medium","Hard"]); n=st.slider("Questions",3,8,5)
    if st.button("🚀 Generate Quiz",use_container_width=True):
        q,live=make_quiz(x["topic"],d,n); st.session_state.q=q; st.session_state.meta=x; st.session_state.live=live; st.session_state.done=False
    if "q" not in st.session_state:return
    if st.session_state.live: st.success("✨ Quiz generated with Gemini AI.")
    else: st.info("ℹ️ AI is temporarily unavailable. RecallIQ is using its built-in quiz engine. No error is shown.")
    ans={}
    for i,q in enumerate(st.session_state.q):
        st.markdown(f"### Q{i+1}. {q['question']}")
        z=st.radio("Choose one",q["options"],key=f"qq{i}"); ans[i]=q["options"].index(z)
    if st.button("✅ Submit Quiz",use_container_width=True):
        score=sum(ans[i]==int(q["answer"]) for i,q in enumerate(st.session_state.q))
        total=len(st.session_state.q); x=st.session_state.meta
        pct=score/total*100
        old=rows("SELECT mastery FROM topics WHERE subject=? AND topic=? LIMIT 1",(x["subject"],x["topic"]))
        if old:
            m=round(float(old[0]["mastery"])*.4+pct*.6,2)
            run("UPDATE topics SET mastery=?,last_revision=?,revision_count=revision_count+1 WHERE subject=? AND topic=?",(m,datetime.now().strftime("%Y-%m-%d %H:%M:%S"),x["subject"],x["topic"]))
        run("INSERT INTO quiz_results(subject,topic,score,total,percentage,created_at) VALUES(?,?,?,?,?,?)",(x["subject"],x["topic"],score,total,pct,datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        st.session_state.done=True; st.session_state.score=score; st.session_state.total=total; st.session_state.ans=ans
    if st.session_state.get("done"):
        p=st.session_state.score/st.session_state.total*100
        (st.success if p>=80 else st.warning if p>=50 else st.error)(f"{'🎉 Excellent' if p>=80 else '👍 Good attempt' if p>=50 else '📚 Needs revision'} — {st.session_state.score}/{st.session_state.total} ({p:.0f}%)")
        for i,q in enumerate(st.session_state.q):
            (st.success if st.session_state.ans[i]==int(q["answer"]) else st.error)(f"Q{i+1}: {'Correct ✓' if st.session_state.ans[i]==int(q['answer']) else 'Incorrect ✗'}")
            st.caption(q.get("explanation","Review this concept."))

def remember():
    st.title("💡 How to Remember"); st.write("Simple explanations, mnemonics and active recall.")
    ts=topics()
    if not ts: st.info("Add a topic first."); return
    labels=[f'{x["subject"]} → {x["topic"]}' for x in ts]; ch=st.selectbox("Choose Topic",labels); t=ts[labels.index(ch)]["topic"]
    if st.button("🧠 Generate Memory Guide",use_container_width=True):
        with st.spinner("Creating your memory guide..."): st.session_state.guide=make_guide(t)
    if "guide" not in st.session_state:return
    g=st.session_state.guide
    if isinstance(g,str):
        st.success("✨ AI guide ready."); st.markdown(g)
    else:
        st.info("ℹ️ AI is temporarily unavailable. RecallIQ generated a built-in guide so your study session continues.")
        st.subheader("📌 Key Points")
        for p in g["points"]: st.markdown("- "+p)
        st.subheader("🧠 Memory Trick"); st.write(g["trick"])
        st.subheader("💬 Simple Explanation"); st.write(g["simple"])
        st.subheader("🌍 Real-Life Example"); st.write(g["example"])
        st.subheader("⚡ 1-Minute Revision"); st.write(g["revision"])
        st.subheader("🔄 Active Recall")
        for q in g["questions"]: st.markdown("- "+q)
        st.subheader("🃏 Flashcards")
        for i,q in enumerate(g["questions"],1): st.markdown(f"**Card {i}:** {q}")
        st.subheader("🎤 Teach-Back"); st.info(f"Explain **{t}** as if teaching it to a school student.")

def revision():
    st.title("📅 Smart Revision")
    ts=topics()
    if not ts: st.info("Add topics first."); return
    out=[]
    for x in ts:
        m=float(x["mastery"]); mins=10 if m>=70 else 15 if m>=40 else 25
        if x["difficulty"]=="Hard": mins+=5
        if x["last_revision"]:
            try: days=(datetime.now()-datetime.strptime(x["last_revision"],"%Y-%m-%d %H:%M:%S")).days
            except Exception: days=999
        else: days=999
        p="High" if m<40 or days>=7 else "Medium" if m<70 else "Low"
        out.append([x["subject"],x["topic"],m,x["difficulty"],days,p,mins])
    d=pd.DataFrame(out,columns=["Subject","Topic","Mastery %","Difficulty","Days Since Revision","Priority","Suggested Minutes"])
    d["_o"]=d.Priority.map({"High":0,"Medium":1,"Low":2}); d=d.sort_values("_o").drop(columns="_o")
    st.dataframe(d,use_container_width=True,hide_index=True)
    st.subheader("🔥 Today's Focus")
    for _,r in d[d.Priority=="High"].head(3).iterrows():
        st.markdown(f'<div class="card"><div class="title">🔥 {r.Topic}</div>{r.Subject} · {r["Mastery %"]:.0f}% mastery · {r["Suggested Minutes"]} minutes</div>',unsafe_allow_html=True)

def exam():
    st.title("🎯 Exam Mode")
    with st.form("exam"):
        n=st.text_input("Exam Name"); d=st.date_input("Exam Date",date.today()+timedelta(days=14))
        ok=st.form_submit_button("➕ Save Exam",use_container_width=True)
    if ok:
        if not n.strip(): st.warning("Enter an exam name.")
        else: run("INSERT INTO exams(exam_name,exam_date) VALUES(?,?)",(n.strip(),d.isoformat())); st.success("Exam saved!"); st.rerun()
    for e in exams():
        left=(date.fromisoformat(e["exam_date"])-date.today()).days
        msg="🔥 Exam is today!" if left==0 else "Exam completed" if left<0 else f"⏳ {left} days remaining"
        st.markdown(f'<div class="card"><div class="title">🎯 {e["exam_name"]}</div>Date: {e["exam_date"]}<br>{msg}</div>',unsafe_allow_html=True)

def progress():
    st.title("📊 Progress & Insights")
    ts=topics(); qs=quizzes()
    if ts:
        d=pd.DataFrame(ts); f=px.bar(d,x="topic",y="mastery",color="subject",title="Topic Mastery")
        f.update_layout(paper_bgcolor="#0B0F19",plot_bgcolor="#0B0F19",font_color="#F8FAFC")
        st.plotly_chart(f,use_container_width=True)
    if qs:
        q=pd.DataFrame(qs).sort_values("created_at"); f=px.line(q,x="created_at",y="percentage",markers=True,title="Quiz Performance")
        f.update_layout(paper_bgcolor="#0B0F19",plot_bgcolor="#0B0F19",font_color="#F8FAFC")
        st.plotly_chart(f,use_container_width=True); st.dataframe(q,use_container_width=True,hide_index=True)
    if not ts and not qs: st.info("Your progress will appear here after you add topics and take quizzes.")

def assistant():
    st.title("🤖 AI Study Assistant")
    q=st.text_area("Ask RecallIQ",placeholder="Explain KNN in simple words...")
    if st.button("✨ Ask RecallIQ",use_container_width=True):
        if not q.strip(): st.warning("Please enter a question."); return
        with st.spinner("Thinking..."): text=ai(f"You are RecallIQ, a student study assistant. Answer simply with short points and an example when useful.\nQuestion: {q}")
        if text: st.markdown(text)
        else: st.info("AI is temporarily unavailable. No error occurred. Try How to Remember, AI Quiz or Smart Revision.")

def side():
    st.sidebar.markdown('<div style="text-align:center;padding:10px"><div style="font-size:30px;font-weight:800;color:#F8FAFC">🧠 RecallIQ</div><div style="color:#64748B">Learn • Recall • Improve</div></div>',unsafe_allow_html=True)
    pages=["🏠 Dashboard","📚 My Learning","🧠 AI Quiz","💡 How to Remember","📅 Smart Revision","🎯 Exam Mode","📊 Progress","🤖 AI Assistant"]
    if "page" not in st.session_state: st.session_state.page=pages[0]
    for p in pages:
        if st.sidebar.button(p,use_container_width=True): st.session_state.page=p; st.rerun()
    st.sidebar.markdown("---")
    st.sidebar.caption("RecallIQ • Personalized Learning Assistant")
    st.sidebar.caption("AI errors are handled silently.")

def main():
    side()
    p=st.session_state.page
    {"🏠 Dashboard":dashboard,"📚 My Learning":learning,"🧠 AI Quiz":quiz,
     "💡 How to Remember":remember,"📅 Smart Revision":revision,
     "🎯 Exam Mode":exam,"📊 Progress":progress,"🤖 AI Assistant":assistant}[p]()

if __name__=="__main__": main()
