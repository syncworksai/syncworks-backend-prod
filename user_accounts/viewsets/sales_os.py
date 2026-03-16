from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from user_accounts.models.sales_os import (
    Prospect,
    ProspectAttachment,
    ProspectStage,
    SalesEvent,
    SalesPipeline,
    SalesPipelineMember,
)

from user_accounts.serializers.sales_os import (
    ProspectAttachmentSerializer,
    ProspectSerializer,
    ProspectStageSerializer,
    SalesEventSerializer,
    SalesPipelineMemberSerializer,
    SalesPipelineSerializer,
)


def _is_platform_admin(user) -> bool:
    return bool(getattr(user, "is_platform_admin", False) or getattr(user, "is_superuser", False))


def _user_can_access_pipeline(user, pipeline_id: int) -> bool:
    if _is_platform_admin(user):
        return True
    return SalesPipeline.objects.filter(
        id=pipeline_id
    ).filter(
        Q(created_by=user) | Q(members__user=user, members__is_active=True)
    ).exists()


def _get_default_stage_defs():
    return [
        ("New", 0, False, False),
        ("Open", 10, False, False),
        ("Scheduled", 20, False, False),
        ("Working", 30, False, False),
        ("Needs Info", 40, False, False),
        ("Awaiting Change", 50, False, False),
        ("Won", 90, True, False),
        ("Lost", 100, False, True),
    ]


class SalesPipelineViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = SalesPipeline.objects.all()
    serializer_class = SalesPipelineSerializer

    def get_queryset(self):
        user = self.request.user

        if _is_platform_admin(user):
            return SalesPipeline.objects.all()

        member_pipeline_ids = (
            SalesPipelineMember.objects.filter(
                user=user,
                is_active=True,
            ).values_list("pipeline_id", flat=True)
        )

        return (
            SalesPipeline.objects.filter(Q(id__in=member_pipeline_ids) | Q(created_by=user))
            .distinct()
        )

    @action(detail=False, methods=["get"], url_path="me")
    def me(self, request):
        qs = self.get_queryset().order_by("-updated_at", "-id")
        data = SalesPipelineSerializer(qs, many=True).data
        return Response(
            {
                "results": data,
                "count": qs.count(),
                "value": data,
                "Count": qs.count(),
            }
        )

    @action(detail=True, methods=["get"], url_path="metrics")
    def metrics(self, request, pk=None):
        pipeline = self.get_object()

        assigned_member_id = request.query_params.get("assigned_member_id")
        pqs = Prospect.objects.filter(pipeline_id=pipeline.id)

        if assigned_member_id is not None:
            if str(assigned_member_id).strip() == "":
                pqs = pqs.filter(assigned_member__isnull=True)
            else:
                pqs = pqs.filter(assigned_member_id=assigned_member_id)

        now = timezone.now()
        since_30 = now - timedelta(days=30)

        total_prospects = pqs.count()
        open_prospects = pqs.filter(status=Prospect.STATUS_OPEN).count()

        created_30d = pqs.filter(created_at__gte=since_30).count()
        won_30d = pqs.filter(status=Prospect.STATUS_WON, updated_at__gte=since_30).count()

        conversion_rate_30d = (won_30d / created_30d) if created_30d else 0.0

        return Response(
            {
                "pipeline": {
                    "id": pipeline.id,
                    "name": pipeline.name,
                    "is_locked": bool(getattr(pipeline, "is_locked", False)),
                },
                "total_prospects": total_prospects,
                "open_prospects": open_prospects,
                "won_30d": won_30d,
                "conversion_rate_30d": conversion_rate_30d,
            }
        )

    @action(detail=True, methods=["get"], url_path="leaderboard")
    def leaderboard(self, request, pk=None):
        pipeline = self.get_object()
        assigned_member_id = request.query_params.get("assigned_member_id")

        now = timezone.now()
        since_30 = now - timedelta(days=30)

        members = SalesPipelineMember.objects.filter(pipeline_id=pipeline.id, is_active=True)

        if assigned_member_id is not None and str(assigned_member_id).strip():
            members = members.filter(id=assigned_member_id)

        member_ids = list(members.values_list("id", flat=True))

        pqs = Prospect.objects.filter(pipeline_id=pipeline.id)

        created_rows = (
            pqs.filter(created_at__gte=since_30, assigned_member_id__in=member_ids)
            .values("assigned_member_id")
            .annotate(c=Count("id"))
        )
        created_map = {r["assigned_member_id"]: r["c"] for r in created_rows}

        won_rows = (
            pqs.filter(status=Prospect.STATUS_WON, updated_at__gte=since_30, assigned_member_id__in=member_ids)
            .values("assigned_member_id")
            .annotate(c=Count("id"))
        )
        won_map = {r["assigned_member_id"]: r["c"] for r in won_rows}

        ev_rows = (
            SalesEvent.objects.filter(pipeline_id=pipeline.id, start_at__gte=since_30, assigned_member_id__in=member_ids)
            .values("assigned_member_id")
            .annotate(c=Count("id"))
        )
        ev_map = {r["assigned_member_id"]: r["c"] for r in ev_rows}

        rows = []
        for m in members.select_related("user"):
            created_30d = int(created_map.get(m.id, 0))
            won_30d = int(won_map.get(m.id, 0))
            activity_30d = int(ev_map.get(m.id, 0))
            conv = (won_30d / created_30d) if created_30d else 0.0

            display = {
                "name": "",
                "email": "",
            }
            try:
                display["email"] = getattr(m.user, "email", "") or ""
                fn = getattr(m.user, "first_name", "") or ""
                ln = getattr(m.user, "last_name", "") or ""
                display["name"] = (fn + " " + ln).strip() or display["email"] or f"User {m.user_id}"
            except Exception:
                display["name"] = f"Member #{m.id}"

            rows.append(
                {
                    "member_id": m.id,
                    "agent_name": display["name"],
                    "prospects_created_30d": created_30d,
                    "prospects_won_30d": won_30d,
                    "activity_count_30d": activity_30d,
                    "conversion_rate_30d": conv,
                }
            )

        rows.sort(key=lambda r: (r["prospects_won_30d"], r["prospects_created_30d"], r["activity_count_30d"]), reverse=True)

        return Response({"top_10": rows[:10]})

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

        pipeline = serializer.instance

        SalesPipelineMember.objects.get_or_create(
            pipeline=pipeline,
            user=self.request.user,
            defaults={"role": SalesPipelineMember.ROLE_OWNER, "is_active": True, "is_active_seat": True},
        )

        if not ProspectStage.objects.filter(pipeline=pipeline).exists():
            for (name, sort_order, is_won, is_lost) in _get_default_stage_defs():
                ProspectStage.objects.create(
                    pipeline=pipeline,
                    name=name,
                    sort_order=sort_order,
                    is_won=is_won,
                    is_lost=is_lost,
                )


class SalesPipelineMemberViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = SalesPipelineMember.objects.all()
    serializer_class = SalesPipelineMemberSerializer

    def get_queryset(self):
        user = self.request.user
        if _is_platform_admin(user):
            return SalesPipelineMember.objects.all()

        allowed_pipeline_ids = SalesPipeline.objects.filter(
            Q(created_by=user) | Q(members__user=user, members__is_active=True)
        ).values_list("id", flat=True)

        qs = SalesPipelineMember.objects.filter(pipeline_id__in=allowed_pipeline_ids)

        pipeline_id = self.request.query_params.get("pipeline_id")
        if pipeline_id:
            qs = qs.filter(pipeline_id=pipeline_id)

        return qs

    def perform_create(self, serializer):
        user = self.request.user
        pipeline = serializer.validated_data.get("pipeline")

        if _is_platform_admin(user):
            serializer.save()
            return

        can_access = _user_can_access_pipeline(user, pipeline.id)
        if not can_access:
            raise PermissionDenied("No access to this pipeline")

        try:
            my_role = SalesPipelineMember.objects.get(pipeline=pipeline, user=user, is_active=True).role
            if my_role not in [SalesPipelineMember.ROLE_OWNER, SalesPipelineMember.ROLE_MANAGER]:
                raise PermissionDenied("Only Owner/Manager can add members")
        except SalesPipelineMember.DoesNotExist:
            if pipeline.created_by_id != user.id:
                raise PermissionDenied("Only Owner/Manager can add members")

        serializer.save()


class ProspectStageViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = ProspectStage.objects.all()
    serializer_class = ProspectStageSerializer

    def get_queryset(self):
        user = self.request.user
        pipeline_id = self.request.query_params.get("pipeline_id")

        qs = ProspectStage.objects.all()

        if pipeline_id:
            qs = qs.filter(pipeline_id=pipeline_id)

        if _is_platform_admin(user):
            return qs

        return qs.filter(
            Q(pipeline__created_by=user) | Q(pipeline__members__user=user, pipeline__members__is_active=True)
        ).distinct()


class ProspectViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = Prospect.objects.all()
    serializer_class = ProspectSerializer

    def get_queryset(self):
        user = self.request.user
        pipeline_id = self.request.query_params.get("pipeline_id")
        stage_id = self.request.query_params.get("stage_id")
        assigned_member_id = self.request.query_params.get("assigned_member_id")
        q = (self.request.query_params.get("q") or "").strip()

        qs = Prospect.objects.all()

        if pipeline_id:
            qs = qs.filter(pipeline_id=pipeline_id)

        if stage_id:
            qs = qs.filter(stage_id=stage_id)

        if assigned_member_id is not None:
            if str(assigned_member_id).strip() == "":
                qs = qs.filter(assigned_member__isnull=True)
            else:
                qs = qs.filter(assigned_member_id=assigned_member_id)

        if q:
            qs = qs.filter(
                Q(full_name__icontains=q)
                | Q(name__icontains=q)
                | Q(email__icontains=q)
                | Q(phone__icontains=q)
                | Q(company__icontains=q)
                | Q(notes__icontains=q)
            )

        if _is_platform_admin(user):
            return qs

        return qs.filter(
            Q(pipeline__created_by=user) | Q(pipeline__members__user=user, pipeline__members__is_active=True)
        ).distinct()

    def perform_create(self, serializer):
        instance = serializer.save(created_by=self.request.user)

        try:
            if instance.stage_id:
                st = ProspectStage.objects.filter(id=instance.stage_id).first()
                if st and st.is_won:
                    instance.status = Prospect.STATUS_WON
                    instance.save(update_fields=["status", "updated_at"])
                elif st and st.is_lost:
                    instance.status = Prospect.STATUS_LOST
                    instance.save(update_fields=["status", "updated_at"])
        except Exception:
            pass


class ProspectAttachmentViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = ProspectAttachment.objects.all()
    serializer_class = ProspectAttachmentSerializer

    def get_queryset(self):
        user = self.request.user
        prospect_id = self.request.query_params.get("prospect_id")

        qs = ProspectAttachment.objects.all()
        if prospect_id:
            qs = qs.filter(prospect_id=prospect_id)

        if _is_platform_admin(user):
            return qs

        return qs.filter(
            Q(prospect__pipeline__created_by=user)
            | Q(prospect__pipeline__members__user=user, prospect__pipeline__members__is_active=True)
        ).distinct()

    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)


class SalesEventViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    queryset = SalesEvent.objects.all()
    serializer_class = SalesEventSerializer

    def get_queryset(self):
        user = self.request.user
        pipeline_id = self.request.query_params.get("pipeline_id")
        assigned_member_id = self.request.query_params.get("assigned_member_id")
        start = self.request.query_params.get("start")
        end = self.request.query_params.get("end")

        qs = SalesEvent.objects.all()

        if pipeline_id:
            qs = qs.filter(pipeline_id=pipeline_id)

        if assigned_member_id is not None:
            if str(assigned_member_id).strip() == "":
                qs = qs.filter(assigned_member__isnull=True)
            else:
                qs = qs.filter(assigned_member_id=assigned_member_id)

        if start:
            try:
                qs = qs.filter(end_at__gte=start)
            except Exception:
                pass
        if end:
            try:
                qs = qs.filter(start_at__lte=end)
            except Exception:
                pass

        if _is_platform_admin(user):
            return qs

        allowed_pipeline_ids = SalesPipeline.objects.filter(
            Q(created_by=user) | Q(members__user=user, members__is_active=True)
        ).values_list("id", flat=True)

        return qs.filter(pipeline_id__in=allowed_pipeline_ids).distinct()

    def perform_create(self, serializer):
        pipeline = serializer.validated_data.get("pipeline")
        if not pipeline:
            raise PermissionDenied("pipeline is required")

        if not _user_can_access_pipeline(self.request.user, pipeline.id):
            raise PermissionDenied("No access to this pipeline")

        if bool(getattr(pipeline, "is_locked", False)):
            raise PermissionDenied("Pipeline locked (read-only)")

        serializer.save(created_by=self.request.user)


class SalesKPIViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]

    def list(self, request):
        user = request.user
        pipeline_id = request.query_params.get("pipeline_id")

        pipelines_qs = SalesPipeline.objects.all()
        prospects_qs = Prospect.objects.all()

        if not _is_platform_admin(user):
            pipelines_qs = pipelines_qs.filter(
                Q(created_by=user) | Q(members__user=user, members__is_active=True)
            ).distinct()
            prospects_qs = prospects_qs.filter(pipeline__in=pipelines_qs)

        if pipeline_id:
            pipelines_qs = pipelines_qs.filter(id=pipeline_id)
            prospects_qs = prospects_qs.filter(pipeline_id=pipeline_id)

        status_counts = prospects_qs.values("status").annotate(c=Count("id"))
        by_status = {row["status"]: row["c"] for row in status_counts}

        return Response(
            {
                "pipeline_id": int(pipeline_id) if pipeline_id else None,
                "pipelines_total": pipelines_qs.count(),
                "prospects_total": prospects_qs.count(),
                "prospects_open": by_status.get(Prospect.STATUS_OPEN, 0),
                "prospects_won": by_status.get(Prospect.STATUS_WON, 0),
                "prospects_lost": by_status.get(Prospect.STATUS_LOST, 0),
            }
        )