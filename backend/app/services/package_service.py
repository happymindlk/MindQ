from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.package import Package
from app.models.assessment import Assessment
from app.models.candidate import Candidate


class PackageService:
    """Read helpers used by the candidate flow and report generation.

    Package/assessment creation moved to the Supabase RPC `create_package`
    (frontend/src/lib/adminApi.js), which runs under RLS on the HR path.
    """

    @staticmethod
    async def get_packages(session: AsyncSession, corporate_id: UUID | None = None):
        stmt = (
            select(Package, func.count(Candidate.id).label("candidate_count"))
            .outerjoin(Candidate, Candidate.package_id == Package.id)
            .group_by(Package.id)
        )
        if corporate_id:
            stmt = stmt.where(Package.corporate_id == corporate_id)
        result = await session.execute(stmt)
        packages = []
        for pkg, count in result.all():
            pkg.candidate_count = count
            packages.append(pkg)
        return packages

    @staticmethod
    async def get_package(session: AsyncSession, package_id: UUID):
        stmt = (
            select(Package, func.count(Candidate.id).label("candidate_count"))
            .outerjoin(Candidate, Candidate.package_id == Package.id)
            .where(Package.id == package_id)
            .group_by(Package.id)
        )
        result = await session.execute(stmt)
        row = result.first()
        if row:
            pkg, count = row
            pkg.candidate_count = count
            return pkg
        return None

    @staticmethod
    async def get_assessments(session: AsyncSession, package_id: UUID):
        result = await session.execute(
            select(Assessment).where(Assessment.package_id == package_id).order_by(Assessment.position)
        )
        return result.scalars().all()
