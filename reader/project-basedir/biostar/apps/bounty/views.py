import time

from django.shortcuts import render
from django.views.generic import  TemplateView
from django.http import HttpResponseRedirect
from django.core.urlresolvers import reverse

from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Field, Fieldset, Div, Submit, ButtonHolder

from biostar.apps.posts.models import Post
from biostar.apps.bounty.models import Bounty
from biostar.apps.util import view_helpers
from biostar.apps.util import ln

from common import json_util
from common.log import logger

class BontyForm(forms.Form):
    FIELDS = ["amt"]

    amt = forms.CharField(
        widget=forms.NumberInput,
        label="Amount (in sats)",
        required=True,
        error_messages={
            'required': "Bounty amount is required"
        },
        max_length=20, min_length=1,
        validators=[],
        help_text="Amount of sats to start or increase the bounty",
    )

    def __init__(self, *args, **kwargs):
        super(BontyForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                'Bounty',
                'amt'
            ),
            ButtonHolder(
                Submit('submit', 'Preview')
            )
        )


class BountyFormView(TemplateView):
    template_name = "bounty_form.html"
    form_class = BontyForm

    def get_context_data(self, **kwargs):
        context = super(BountyFormView, self).get_context_data(**kwargs)

        pid = kwargs["pid"]
        context["pid"] = pid

        logger.debug("New bounty form for post_id {}".format(pid))

        post = Post.objects.get(pk=pid)
        context["post"] = post


        # TODO: put into a shard function get_bounty_sats
        bounty_sats = 0
        for b in Bounty.objects.filter(post_id=context["post"], is_active=True, is_payed=False):
            bounty_sats += b.amt

        if bounty_sats == 0:
            bounty_sats = None

        context["previous_bounty_sats"] = bounty_sats

        return context

    def get(self, request, *args, **kwargs):
        form = self.form_class(initial={"amt": 10000})

        try:
            context = self.get_context_data(**kwargs)
        except Exception as e:
            logger.exception(e)
            raise

        context['form'] = form

        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        try:
            context = self.get_context_data(**kwargs)
        except Exception as e:
            logger.exception(e)
            raise

        # Validating the form.
        form = self.form_class(request.POST)
        if not form.is_valid():
            try:
                context = self.get_context_data(**kwargs)
            except Exception as e:
                logger.exception(e)
                raise

            context['form'] = form
            context['errors_detected'] = True

            return render(
                request,
                self.template_name,
                context
            )

        pid = context["pid"]
        amt = form.cleaned_data.get("amt")

        logger.debug("Bounty amount is {} for post_id {}".format(amt, pid))
        memo = {
            "action": "Bounty",
            "post_id": pid,
            "amt": amt,
            "unixtime": int(time.time())
        }

        memo_serialized = json_util.serialize_memo(memo)

        return HttpResponseRedirect(reverse("bounty-publish", kwargs=dict(memo=memo_serialized)))


class BountyPublishView(TemplateView):
    template_name = "bounty_publish.html"

    def get_context_data(self, **kwargs):
        context = super(BountyPublishView, self).get_context_data(**kwargs)

        inovice_details = view_helpers.gen_invoice(
            memo=context["memo"],
            node_id=context.get("node_id"),
        )

        for i in ["pay_req", "payment_amount", "open_channel_url", "next_node_url", "node_name", "node_id"]:
            context[i] = inovice_details[i]

        return context

    def get(self, request, *args, **kwargs):
        try:
            context = self.get_context_data(**kwargs)
        except ln.LNUtilError as msg:
            logger.exception(msg)
            # empty context will trigger "Sorry, no LN Nodes are currently available"
            context = {}
            return render(request, self.template_name, context)

        except Exception as e:
            logger.exception(e)
            raise

        post_id = view_helpers.check_invoice(memo=context.get("memo"), node_id=context.get("node_id"))
        if post_id:
            return view_helpers.post_redirect(pid=post_id, request=request, permanent=False)

        return render(request, self.template_name, context)
