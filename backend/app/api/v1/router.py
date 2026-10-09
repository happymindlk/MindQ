from fastapi import APIRouter
from .candidate import router as candidate_router
from .candidate_reports import router as candidate_reports_router
from .reports import router as reports_router
from .notifications import router as notifications_router
from .chat import router as chat_router
from .support import router as support_router
from .track import router as track_router
from .jobs import router as jobs_router
from .corporates import router as corporates_router
from .packages import router as packages_router
from .client import router as client_router
from .admin_ops import router as admin_ops_router
from .library import router as library_router

api_router = APIRouter()
# Most HR admin CRUD (packages list / candidates) is served by Supabase via
# supabase-js + RLS. Automated package generation + save run through FastAPI so Gemini
# keys stay server-side and tenancy is enforced via the HR JWT corporate_id.
api_router.include_router(candidate_router, prefix="/candidate", tags=["candidate"])
api_router.include_router(
    candidate_reports_router, prefix="/candidates", tags=["candidate-reports"]
)
api_router.include_router(reports_router, prefix="/admin/candidates", tags=["reports"])
api_router.include_router(notifications_router, prefix="/admin/candidates", tags=["notifications"])
api_router.include_router(jobs_router, prefix="/admin/jobs", tags=["jobs"])
api_router.include_router(corporates_router, prefix="/corporates", tags=["corporates"])
api_router.include_router(packages_router, prefix="/packages", tags=["packages"])
api_router.include_router(admin_ops_router, prefix="/admin", tags=["admin"])
api_router.include_router(library_router, prefix="/library", tags=["library"])
api_router.include_router(client_router, prefix="/client", tags=["client"])
api_router.include_router(chat_router, prefix="/chat", tags=["chat"])
api_router.include_router(support_router, prefix="/support", tags=["support"])
api_router.include_router(track_router, prefix="/track", tags=["track"])
