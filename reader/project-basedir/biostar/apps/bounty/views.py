import time

from django.shortcuts import render
from django.views.generic import  TemplateView
from django.http import HttpResponseRedirect
from django.core.urlresolvers import reverse

from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Field, Fieldset, Div, Submit, ButtonHolder

from biostar.apps.util import view_helpers

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

        return context

    def get(self, request, *args, **kwargs):
        form = self.form_class(initial={"amt": 10000})

        return render(request, self.template_name, {'form': form})

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

        inovice_details = view_helpers.gen_invoice(publish_url="bounty-publish-node-selected", memo=context["memo"])

        # TODO: if payment fails, "pay_req" will not be present so this will throw a KeyError, make more user friendly
        for i in ["pay_req", "payment_amount", "open_channel_url", "next_node_url", "node_name", "node_id"]:
            context[i] = inovice_details[i]

        return context

    def get(self, request, *args, **kwargs):
        try:
            context = self.get_context_data(**kwargs)
        except Exception as e:
            logger.exception(e)
            raise

        post_id = view_helpers.check_invoice(memo=context.get("memo"), node_id=context.get("node_id"))
        if post_id:
            return view_helpers.post_redirect(pid=post_id, request=request, permanent=False)

        return render(request, self.template_name, context)
