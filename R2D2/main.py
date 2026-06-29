from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
#from meetingAssistantDemoSolution import start_r2d2_workflow
from r2d2_autogen_bot import start_r2d2_workflow

app = FastAPI(title="R2D2 Agentic API", version="1.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change to specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AgentInput(BaseModel):
    UserEmail: str
    Transcript: str

@app.get("/")
def read_root():    
    return {"Hello": "World", "status": "FastAPI is running!", "api_version": "1.0.0"}

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "r2d2-agentic-api"}

@app.post("/invoke_r2d2_agent/")
async def invoke_r2d2_agent(agent_input: AgentInput):
    # Fire the agentic workflow without exposing instructions or agent selection
    response = await start_r2d2_workflow(user_email=agent_input.UserEmail, transcript=agent_input.Transcript)
    return {        
        "response": response
    }

@app.get("/")
def read_root():    
    return {"Hello": "World"}

@app.get("/test")
def read_root():    
    return {"Hello": "Test"}