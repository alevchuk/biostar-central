# Create your views here.
import re
import json
import langdetect

from django.shortcuts import render_to_response
from django.views.generic import TemplateView, DetailView, ListView, FormView, UpdateView
from django import forms
from django.core.urlresolvers import reverse
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Field, Fieldset, Div, Submit, ButtonHolder
from django.shortcuts import render
from django import shortcuts
from django.http import HttpResponseRedirect, HttpResponse, HttpRequest,  HttpResponseNotFound
from datetime import datetime
from django.utils.timezone import utc
from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings
from django.core.exceptions import ValidationError

from django.template.loader import render_to_string

from common.const import OrderedDict
from common import general_util
from common import json_util
from common import html_util
from common import validators

from biostar.apps.util import ln
from biostar.apps.users.models import User
from biostar.apps.posts.models import PostPreview, Post
from biostar.apps.util import view_helpers

from common.log import logger


class PostViewException(Exception):
    pass


def english_only(text):
    try:
        text.decode('ascii')
    except Exception:
        raise ValidationError('Title may only contain plain text (ASCII) characters')


def valid_language(text):
    supported_languages = settings.LANGUAGE_DETECTION
    if supported_languages:
        lang = langdetect.detect(text)
        if lang not in supported_languages:
            raise ValidationError(
                    'Language "{0}" is not one of the supported languages {1}!'.format(lang, supported_languages))


def valid_title(text):
    "Validates form input for tags"
    text = text.strip()
    if not text:
        raise ValidationError('Please enter a title')

    if len(text) < 10:
        raise ValidationError('The title is too short')

    words = text.split(" ")
    if len(words) < 3:
        raise ValidationError('More than two words please.')


def valid_tag(text):
    "Validates form input for tags"
    text = text.strip()
    if not text:
        raise ValidationError('Please enter at least one tag')
    if len(text) > 50:
        raise ValidationError('Tag line is too long (50 characters max)')
    words = text.split(",")
    if len(words) > 5:
        raise ValidationError('You have too many tags (5 allowed)')

class ContentWidget(forms.Textarea):
    TEMPLATE = "pagedown_widget.html"

    def render(self, name, value, attrs=None):
        attrs = attrs if attrs else {}
        params = dict(
            value=(value or ''),
            rows=attrs.get('class', ''),
            klass=attrs.get('class', ''),
            maxlength=settings.MAX_CONTENT
        )
        return render_to_string(self.TEMPLATE, params)


class LongForm(forms.Form):
    FIELDS = "title content post_type tag_val".split()

    POST_CHOICES = [
        (Post.QUESTION, "Question"),
        (Post.META_QUESTION, "Meta (a question/discussion about this website)")
    ]

    title = forms.CharField(
        label="Post Title",
        required=True,
        max_length=settings.MAX_TITLE,
        min_length=10,
        validators=[valid_title, english_only, validators.validate_signable_field],
        help_text="Descriptive titles promote better answers (maximum of {} characters)".format(settings.MAX_TITLE))

    post_type = forms.ChoiceField(
        label="Post Type",
        required=True,
        choices=POST_CHOICES, help_text="Select a post type: Question, Job Offer, Tutorial, Blog, Meta")

    tag_val = forms.CharField(
        label="Post Tags",
        required=True,
        validators=[valid_tag],
        help_text="Choose one or more tags to match the topic. To create a new tag just type it in and press ENTER.",
    )

    # note: max_length is larger than MAX_MEMO_SIZE because max_length applies before compression
    # max_length is here to guide the user during editing, while MAX_MEMO_SIZE is the final
    # insurance that the memo will fit into the lightning payment
    content = forms.CharField(
        widget=ContentWidget,
        validators=[valid_language],
        min_length=80,
        max_length=settings.MAX_CONTENT,
        label="Enter your post below"
    )

    def __init__(self, *args, **kwargs):
        super(LongForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_class = "post-form"
        self.helper.layout = Layout(
            Fieldset(
                'Post Form',
                Field('title', maxlength=settings.MAX_TITLE),
                Field('post_type'),
                Field('tag_val'),
                Field('content'),
            ),
            ButtonHolder(
                Submit('submit', 'Preview')
            )
        )

    def clean(self):
        cleaned_data = super(LongForm, self).clean()

        parent_post_id = cleaned_data.get("parent_post_id")

        if parent_post_id:

            # Find the parent.
            try:
                parent = Post.objects.get(pk=parent_post_id)
            except ObjectDoesNotExist, exc:
                raise ValidationError(
                    "Parent post {} does not exist. Perhaps it was deleted request".format(
                        parent_post_id
                    )
                )

            post_preview = PostPreview(
                parent_post_id = parent_post_id,
                title = parent.title,
                tag_val = parent.tag_val,
                tag_value = html_util.split_tags(parent.tag_val),
                content=cleaned_data.get('content'),
                type=int(cleaned_data.get('post_type')),
                date=general_util.now()
            )
        else:
            post_preview = PostPreview(
                title=cleaned_data.get('title'),
                content=cleaned_data.get('content'),
                tag_val=cleaned_data.get('tag_val'),
                type=int(cleaned_data.get('post_type')),
                date=general_util.now()
            )

        try:
            serialized = post_preview.serialize_memo()

        except json_util.MemoTooLarge as err:
            raise ValidationError(
                (
                    '%(msg)s. '
                    'Sorry, we are not going to be able to fit this into a lightning payment memo.'
                ),
                code='too_big_serialized',
                params={
                    'max_size': settings.MAX_MEMO_SIZE,
                    'msg': "{0}".format(err)
                    },
            )

        return cleaned_data


class ShortForm(forms.Form):
    FIELDS = ["content", "parent_post_id"]

    content = forms.CharField(
        widget=ContentWidget,
        min_length=20,
        max_length=settings.MAX_CONTENT
    )

    def __init__(self, *args, **kwargs):
        super(ShortForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                'Post',
                'content'
            ),
            ButtonHolder(
                Submit('submit', 'Preview')
            )
        )


class SignMessageForm(forms.Form):
    FIELDS = ["signature"]

    signature = forms.CharField(
        widget=forms.Textarea,
        label="Signature",
        required=True,
        error_messages={
            'required': (
                "Signature is optional, yet you clicked \"Check\" and did not provide any Signature. "
                "If you want to post unsigned then click on \"Get Invoice\" at the bottom of this page"
            )
        },
        max_length=200, min_length=10,
        validators=[validators.pre_validate_signature],
        help_text="JSON output of the signmessage command or just text of the signature")

    def __init__(self, *args, **kwargs):
        if "memo" in kwargs:
            memo = kwargs.pop("memo")
        else:
            memo = kwargs.get("initial").get("memo")

        memo_deserialized = json_util.deserialize_memo(memo)
        action = memo_deserialized.get("action")

        super(SignMessageForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()


        if action == "Accept":
            self.signature = forms.CharField(
                widget=forms.Textarea,
                label="Signature",
                required=True,
                error_messages={
                    'required': (

                    )
                },
                max_length=200, min_length=10,
                validators=[validators.pre_validate_signature],
                help_text="JSON output of the signmessage command or just text of the signature"
            )

            self.helper.layout = Layout(
                Field('signature', rows="4"),
                ButtonHolder(
                    Submit('submit', 'Accept Answer')
                )
            )

            self.helper.form_action = reverse(
                "accept-preview",
                kwargs=dict(memo=memo)
            )
        else:

            self.helper.layout = Layout(
                Field('signature', rows="4"),
                ButtonHolder(
                    Submit('submit', 'Sign')
                )
            )

            self.helper.form_action = reverse(
                "post-preview",
                kwargs=dict(memo=memo)
            )

def parse_tags(category, tag_val):
    pass


class NewPost(FormView):
    form_class = LongForm
    template_name = "post_edit.html"


    def get_context_data(self, **kwargs):
        context = super(NewPost, self).get_context_data(**kwargs)
        context['nodes_list'] = [n["node_name"] for n in ln.get_nodes_list()]
        return context

    def get(self, request, *args, **kwargs):

        initial = dict()

        if "memo" in kwargs:
            memo = json_util.deserialize_memo(kwargs["memo"])

            if "parent_post_id" in memo:
                expected_memo_keys = ["parent_post_id", "post_type", "content"]
                self.form_class = ShortForm
            else:
                expected_memo_keys = ["title", "post_type", "tag_val", "content"]

            for key in expected_memo_keys:
                initial[key] = memo[key]
        else:
            # Attempt to prefill from GET parameters
            for key in "title post_type tag_val content".split():
                value = request.GET.get(key)
                if value:
                    initial[key] = value

        try:
            context = self.get_context_data(**kwargs)
        except Exception as e:
            logger.exception(e)
            raise

        context['form'] = self.form_class(initial=initial)
        context['errors_detected'] = False

        return render(request, self.template_name, context)


    def post(self, request, *args, **kwargs):
        if "memo" in kwargs:
            post_preview = PostPreview()

            # Some data comes from memo
            memo = json_util.deserialize_memo(kwargs["memo"])

            if "parent_post_id" in memo:
                self.form_class = ShortForm

                parent_post_id = memo["parent_post_id"]

                # Find the parent.
                try:
                    parent = Post.objects.get(pk=parent_post_id)
                except ObjectDoesNotExist, e:
                    msg = "The post does not exist. Perhaps it was deleted request (Request: %s)".format(request)
                    logger.error(msg)
                    raise PostViewException(msg)

                post_preview.parent_post_id = parent_post_id
                post_preview.title = parent.title
                post_preview.tag_val = parent.tag_val
                post_preview.tag_value = html_util.split_tags(parent.tag_val)
            else:
                post_preview.title = memo["title"]
                post_preview.tag_val = memo["tag_val"]
                post_preview.tag_value = html_util.split_tags(memo["tag_val"])

            post_preview.status = Post.OPEN
            post_preview.type = memo["post_type"]
            post_preview.date = datetime.utcfromtimestamp(memo["unixtime"]).replace(tzinfo=utc)

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

        if "memo" in kwargs:
            # Only new data comes from the HTML form
            post_preview.content = form.cleaned_data.get("content")
            post_preview.html = html_util.parse_html(post_preview.content)
        else:
            # Valid forms start here.
            data = form.cleaned_data

            # All data comes from the HTML form
            post_preview = PostPreview(
                  title=data.get('title'),
                  content=data.get('content'),
                  tag_val=data.get('tag_val'),
                  type=int(data.get('post_type')),
                  date=general_util.now()
            )

        return HttpResponseRedirect(post_preview.get_absolute_url(memo=post_preview.serialize_memo()))


class PostPreviewView(FormView):
    """
    Shows preview of the post and takes an optional signature
    """

    template_name = "post_preview.html"
    form_class = SignMessageForm

    def get_form_kwargs(self):
        view_obj = super(PostPreviewView, self).get_context_data().get("view")
        memo = view_obj.kwargs["memo"]

        return {
            "memo": memo
        }

    def get_model(self, memo):

        post_preview = PostPreview()
        if "parent_post_id" in memo:
            parent_post_id = memo["parent_post_id"]

            # Find the parent.
            try:
                parent = Post.objects.get(pk=parent_post_id)
            except ObjectDoesNotExist, exc:
                logger.error("The post does not exist. Perhaps it was deleted request (Request: %s)", request)
                logger.exception(e)
                raise

            post_preview.parent_post_id = parent_post_id
            post_preview.title = parent.title
            post_preview.tag_val = parent.tag_val
            post_preview.tag_value = html_util.split_tags(parent.tag_val)

        else:
            post_preview.title = memo["title"]
            post_preview.tag_val = memo["tag_val"]
            post_preview.tag_value = html_util.split_tags(memo["tag_val"])

        post_preview.status = Post.OPEN
        post_preview.type = memo["post_type"]
        post_preview.content = memo["content"]
        post_preview.html = html_util.parse_html(memo["content"])
        post_preview.date = datetime.utcfromtimestamp(memo["unixtime"]).replace(tzinfo=utc)

        post_preview.memo = post_preview.serialize_memo()

        post_preview.clean_fields()

        return post_preview

    def get_context_data(self, **kwargs):

        context = super(PostPreviewView, self).get_context_data(**kwargs)

        view_obj = context.get("view")
        memo_serialized = view_obj.kwargs["memo"]

        memo = validators.validate_memo(
            json_util.deserialize_memo(memo_serialized)
        )

        signature = kwargs.get("signature")
        if signature:
            signature = validators.pre_validate_signature(signature)

            result = ln.verifymessage(memo=json.dumps(memo, sort_keys=True), sig=signature)
            if result["valid"]:
                identity_pubkey = result["identity_pubkey"]
                context['user'] = User(id=1, pubkey=identity_pubkey)
                memo["sig"] = signature  # add signature to memo

        if "sig" not in memo:
            context['user'] = User(id=1, pubkey="Unknown")

        # re-serialized because signature was added
        memo_serialized = json_util.serialize_memo(memo)

        post_preview = self.get_model(memo)
        context["memo"] = memo_serialized
        context["post"] = post_preview
        context["publish_url"] = post_preview.get_publish_url(
            memo=memo_serialized
        )

        return context


    def post(self, request, *args, **kwargs):
        """
        POST is for checking signature
        """

        signature = request.POST.get("signature")
        kwargs["signature"] = signature

        view = super(PostPreviewView, self).get(request, *args, **kwargs)

        try:
            view_obj = super(PostPreviewView, self).get_context_data().get("view")
        except Exception as e:
            logger.exception(e)
            raise

        memo_serialized = view_obj.kwargs["memo"]

        memo = validators.validate_memo(
            json_util.deserialize_memo(memo_serialized)
        )

        form = self.form_class(request.POST, memo=memo_serialized)

        errors_detected_skip_other_checks = False
        if signature:
            try:
                signature = validators.pre_validate_signature(signature)
                result = ln.verifymessage(memo=json.dumps(memo, sort_keys=True), sig=signature)
            except ln.LNUtilError as msg:
                result = {
                    "valid": False,
                }
            except ValidationError as msg:
                result = {
                    "valid": False,
                }

            if not result["valid"]:
                # Signature is invalid

                ## See: https://github.com/alevchuk/ln-central/issues/27
                # self.form_class.add_error(
                #     "signature",
                #     ValidationError("Signature is invalid. Try signing latest preview data or delete signature to be anonymous.")
                # )

                post_preview = self.get_model(memo)

                context = {
                    "post": post_preview,
                    "form": form,
                    "user": User.objects.get(pubkey="Unknown"),
                    "errors_detected": True,
                    "show_error_summary": True,
                    "error_summary_list": [
                        "Signature is invalid. Try signing latest preview data or delete signature to be anonymous."
                    ]
                }

                errors_detected_skip_other_checks = True

        if not errors_detected_skip_other_checks:
            try:
                context = self.get_context_data(**kwargs)
            except Exception as e:
                logger.exception(e)
                raise

            context["form"] = form
            context["errors_detected"] = not form.is_valid()

        return render(request, self.template_name, context)


class AcceptPreviewView(FormView):
    """
    Takes a signature required for accepting an answer
    """

    template_name = "accept_preview.html"
    form_class = SignMessageForm

    def get_form_kwargs(self):
        view_obj = super(AcceptPreviewView, self).get_context_data().get("view")
        memo = view_obj.kwargs["memo"]

        return {
            "memo": memo
        }

    def get_model(self, memo):
        post_id = memo.get("post_id")
        post = None

        if post_id:
            try:
                post = Post.objects.get(pk=post_id)
            except ObjectDoesNotExist, exc:
                logger.error("The post does not exist. Perhaps it was deleted request (Request: %s)", request)
                raise

        else:
            msg = "The post is was not provided in the memo (Request: %s)".format(request)
            logger.error(msg)
            raise

        return post

    def get_context_data(self, **kwargs):
        context = super(AcceptPreviewView, self).get_context_data(**kwargs)

        view_obj = context.get("view")
        memo_serialized = view_obj.kwargs["memo"]

        memo = validators.validate_memo(
            json_util.deserialize_memo(memo_serialized)
        )

        signature = kwargs.get("signature")
        if signature:
            signature = validators.pre_validate_signature(signature)

            result = ln.verifymessage(memo=json.dumps(memo, sort_keys=True), sig=signature)
            if result["valid"]:
                identity_pubkey = result["identity_pubkey"]
                context['user'] = User(id=1, pubkey=identity_pubkey)
                memo["sig"] = signature  # add signature to memo

        context['post'] = self.get_model(memo)

        # re-serialized because signature was added
        context['memo'] = json_util.serialize_memo(memo)

        # gives user a friendy error message if no LN nodes are avaialble
        context["nodes_list"] = [n["node_name"] for n in ln.get_nodes_list()]

        return context


    def post(self, request, *args, **kwargs):
        """
        Post is used when checking signature
        """
        signature = request.POST.get("signature")
        kwargs["signature"] = signature

        view = super(AcceptPreviewView, self).get(request, *args, **kwargs)
        view_obj = super(AcceptPreviewView, self).get_context_data().get("view")
        memo_serialized = view_obj.kwargs["memo"]

        memo = validators.validate_memo(
            json_util.deserialize_memo(memo_serialized)
        )
        post = self.get_model(memo)

        form = self.form_class(request.POST, memo=memo_serialized)

        errors_detected_skip_other_checks = False
        if signature:
            signature = validators.pre_validate_signature(signature)

            try:
                result = ln.verifymessage(memo=json.dumps(memo, sort_keys=True), sig=signature)
            except ln.LNUtilError as msg:
                result = {
                    "valid": False,
                }

            if not result["valid"]:
                # Signature is invalid

                ## See: https://github.com/alevchuk/ln-central/issues/27
                # self.form_class.add_error(
                #     "signature",
                #     ValidationError("Signature is invalid. Try signing latest preview data or delete signature to be anonymous.")
                # )

                context = {
                    "post": post,
                    "memo": memo_serialized,
                    "form": form,
                    "errors_detected": True,
                    "show_error_summary": True,
                    "error_summary_list": [
                        "Signature is invalid. Try signing the latest message shown bellow."
                    ]
                }

                errors_detected_skip_other_checks = True

        if not errors_detected_skip_other_checks:
            try:
                context = self.get_context_data(**kwargs)
            except Exception as e:
                logger.exception(e)
                raise

            context["form"] = form

            if not form.is_valid():
                hide_form_errors = False
                if not signature:
                    error_summary_list = [
                        "Signature is required here. Yet when you clicked \"Accept Answer\" the signature was empty."
                    ]
                    hide_form_errors = True
                else:
                    error_summary_list = [
                        "Signature is required here. Yet when you clicked \"Accept Answer\" the signature was invalid."
                    ]

                if hide_form_errors:
                    form = self.form_class(memo=memo_serialized)

                context = {
                    "post": post,
                    "memo": context["memo"],
                    "form": form,
                    "errors_detected": True,
                    "show_error_summary": True,
                    "error_summary_list": error_summary_list
                }
            else:
                # Now check if the signature belongs to author of the question
                pubkey = result["identity_pubkey"]

                if result["identity_pubkey"] == post.parent.author.pubkey:
                    # Looks good! Let's generate an invoice
                    return HttpResponseRedirect(post.get_accept_publish_url(memo=context["memo"]))
                else:
                    context = {
                        "post": post,
                        "memo": context["memo"],
                        "form": form,
                        "errors_detected": True,
                        "show_error_summary": True,
                        "error_summary_list": [
                            "Question has a different author. You can only accept answers if you're the author of the question."
                        ]
                    }

        return render(request, self.template_name, context)


class NewAnswer(FormView):
    """
    Creates a new post.
    """

    form_class = ShortForm
    template_name = "post_edit.html"
    type_map = dict(answer=Post.ANSWER, comment=Post.COMMENT)
    post_type = None

    def get_context_data(self, **kwargs):
        context = super(NewAnswer, self).get_context_data(**kwargs)
        context['nodes_list'] = [n["node_name"] for n in ln.get_nodes_list()]
        return context

    def post(self, request, *args, **kwargs):
        """
        This gets the initial "new answer" request, before the get method
        if everything looks good then we generate the memo (with parent post id)
        and re-direct to preview. If there are errors, we also render this
        back to the user directly from here. See `if not form.is_valid()`
        """

        parent_post_id = int(self.kwargs['pid'])

        # URL sets the type for this new post
        post_type = self.type_map.get(self.post_type)
        assert post_type in [Post.ANSWER, Post.COMMENT], "I only support Answers and Comment types, got: {}".format(post_type)

        # Find the parent.
        try:
            parent = Post.objects.get(pk=parent_post_id)
        except ObjectDoesNotExist, exc:
            logger.error("The post does not exist. Perhaps it was deleted request (Request: %s)", request)
            raise

        # Validating the form.
        form = self.form_class(request.POST)
        if not form.is_valid():
            try:
                context = self.get_context_data(**kwargs)
            except Exception as e:
                logger.exception(e)
                raise

            context["form"] = form
            context["errors_detected"] = True
            return render(request, self.template_name, context)

        # Valid forms start here
        content = form.cleaned_data.get("content")

        post_preview = PostPreview()
        post_preview.parent_post_id = parent_post_id
        post_preview.title = parent.title
        post_preview.tag_val = parent.tag_val
        post_preview.tag_value = html_util.split_tags(parent.tag_val)
        post_preview.status = Post.OPEN
        post_preview.type = post_type
        post_preview.content = content
        post_preview.html = html_util.parse_html(content)
        post_preview.date = general_util.now()
        post_preview.memo = post_preview.serialize_memo()

        post_preview.clean_fields()

        return HttpResponseRedirect(post_preview.get_absolute_url(memo=post_preview.memo))


class EditPost(FormView):
    """
    Edits an existing post.
    """

    # The template_name attribute must be specified in the calling apps.
    template_name = "post_edit.html"
    form_class = LongForm

    def get(self, request, *args, **kwargs):
        initial = {}

        pk = int(self.kwargs['pk'])
        post = Post.objects.get(pk=pk)
        post = auth.post_permissions(request=request, post=post)

        # Check and exit if not a valid edit.
        if not post.is_editable:
            msg = "This user may not modify the post (Request: %s)".format(request)
            logger.error(msg)
            raise EditPostException(msg)

        initial = dict(title=post.title, content=post.content, post_type=post.type, tag_val=post.tag_val)

        # Disable rich editing for preformatted posts
        pre = 'class="preformatted"' in post.content
        form_class = LongForm if post.is_toplevel else ShortForm
        form = form_class(initial=initial)
        return render(request, self.template_name, {'form': form, 'pre': pre})

    def post(self, request, *args, **kwargs):

        pk = int(self.kwargs['pk'])
        post = Post.objects.get(pk=pk)
        post = auth.post_permissions(request=request, post=post)

        # For historical reasons we had posts with iframes
        # these cannot be edited because the content would be lost in the front end
        if "<iframe" in post.content:
            logger.error("This post is not editable because of an iframe! Contact if you must edit it (Request: %s)", request)
            return HttpResponseRedirect(post.get_absolute_url())

        # Check and exit if not a valid edit.
        if not post.is_editable:
            logger.error("This user may not modify the post (Request: %s)", request)
            return HttpResponseRedirect(post.get_absolute_url())

        # Posts with a parent are not toplevel
        form_class = LongForm if post.is_toplevel else ShortForm

        form = form_class(request.POST)
        if not form.is_valid():
            # Invalid form submission.
            return render(request, self.template_name, {'form': form})

        # Valid forms start here.
        data = form.cleaned_data

        # Set the form attributes.
        for field in form_class.FIELDS:
            setattr(post, field, data[field])

        # TODO: fix this oversight!
        post.type = int(data.get('post_type', post.type))

        # This is needed to validate some fields.
        post.save()

        if post.is_toplevel:
            post.add_tags(post.tag_val)

        logger.info("Post updated (Request: %s)", request)

        return HttpResponseRedirect(post.get_absolute_url())

    def get_success_url(self):
        return reverse("user_details", kwargs=dict(pk=self.kwargs['pk']))


def post_redirect(request, pid, permanent=True):
    """
    Redirect to a post

    Permanent means that the browser will remember the request,
    and will redirect instantly without re-checking with the server.
    It can speed things up for the user, may not be the correct
    thing to do in some cases, and makes debugging much harder.
    """
    try:
        post = Post.objects.get(id=pid)
    except Post.DoesNotExist:
        raise Http404
    return shortcuts.redirect(post.get_absolute_url(), permanent=permanent)



class PostPublishView(TemplateView):
    """
    """

    template_name = "post_publish.html"

    def get_context_data(self, **kwargs):
        context = super(PostPublishView, self).get_context_data(**kwargs)
        context = view_helpers.gen_invoice_and_update_context(context)

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

        return super(PostPublishView, self).get(request, *args, **kwargs)


class VoteCustomizeForm(forms.Form):
    FIELDS = ["amt"]

    amt = forms.CharField(
        widget=forms.NumberInput,
        label="Vote Amount (in sats)",
        required=True,
        error_messages={
            'required': "Vote amount is required"
        },
        max_length=20, min_length=1,
        validators=[],
        help_text="Amount of sats to Vote",
    )

    def __init__(self, *args, **kwargs):
        memo = kwargs.pop("memo")

        super(VoteCustomizeForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Fieldset(
                '1 Upvote for 1 sat',
                'amt'
            ),
            ButtonHolder(
                Submit('submit', 'Preview')
            )
        )

        self.helper.form_action = reverse(
                "vote-customize",
                kwargs=dict(memo=memo)
            )


class VoteCustomizeView(TemplateView):
    """
    """

    template_name = "vote_customize.html"
    form_class = VoteCustomizeForm

    def get_context_data(self, **kwargs):
        return super(VoteCustomizeView, self).get_context_data(**kwargs)

    def post(self, request, *args, **kwargs):
        amt = request.POST.get("amt")
        assert amt is not None, "bug"

        memo = kwargs.get("memo")
        assert memo is not None, "bug"


        # change the memo to have new amt
        memo_deserialized = validators.validate_memo(
            json_util.deserialize_memo(memo)
        )

        memo_deserialized["amt"] = amt
        memo = json_util.serialize_memo(memo_deserialized)

        return HttpResponseRedirect(
            reverse(
                "vote-publish",
                kwargs=dict(memo=memo)
            )
        )

    def get(self, request, *args, **kwargs):
        memo = kwargs.get("memo")
        assert memo is not None, "bug"

        form = self.form_class(initial={"amt": 1}, memo=memo)

        try:
            context = self.get_context_data(**kwargs)
        except Exception as e:
            logger.exception(e)
            raise

        context['form'] = form

        return render(request, self.template_name, context)


class VotePublishView(TemplateView):
    """
    """

    template_name = "vote_publish.html"
    form_class = SignMessageForm

    def get_context_data(self, **kwargs):
        context = super(VotePublishView, self).get_context_data(**kwargs)
        context = view_helpers.gen_invoice_and_update_context(context)

        if "memo" in context:
            context["customize_vote_url"] = reverse(
                "vote-customize",
                kwargs=dict(memo=context["memo"])
            )

        return context

    def post(self, request, *args, **kwargs):
        """
        POST is for checking signature of Accept "votes"
        """

        signature = request.POST.get("signature")
        kwargs["signature"] = signature

        try:
            context = super(VotePublishView, self).get_context_data()
            view_obj = context.get("view")

        except Exception as e:
            logger.exception(e)
            raise

        memo_serialized = view_obj.kwargs["memo"]

        memo = validators.validate_memo(
            json_util.deserialize_memo(memo_serialized)
        )


        form = self.form_class(request.POST, memo=memo_serialized)

        errors_detected_skip_other_checks = False
        if signature:
            try:
                signature = validators.pre_validate_signature(signature)
                result = ln.verifymessage(memo=json.dumps(memo, sort_keys=True), sig=signature)
            except ln.LNUtilError as msg:
                result = {
                    "valid": False,
                }
            except ValidationError as msg:
                result = {
                    "valid": False,
                }

            post = AcceptPreviewView().get_model(memo)

            if not result["valid"]:
                # Signature is invalid

                ## See: https://github.com/alevchuk/ln-central/issues/27
                # self.form_class.add_error(
                #     "signature",
                #     ValidationError("Signature is invalid. Try signing latest preview data or delete signature to be anonymous.")
                # )

                context = {
                    "post": post,
                    "form": form,
                    "errors_detected": True,
                    "show_error_summary": True,
                    "error_summary_list": [
                        "Signature is invalid."
                    ]
                }

                errors_detected_skip_other_checks = True
            else:
                # Signature is valid, check if Accept belongs to the author of the post
                assert post.type == Post.ANSWER and post.parent.type == Post.QUESTION, "Accept only Answers to Questions"

                if post.parent.author.pubkey != result["identity_pubkey"]:
                    context = {
                        "post": post,
                        "form": form,
                        "errors_detected": True,
                        "show_error_summary": True,
                        "error_summary_list": [
                            "Signature does not belong to the Question author. Sorry, you can only accept an Answer if you are the author of the Question."
                        ]
                    }

                    errors_detected_skip_other_checks = True


        if not errors_detected_skip_other_checks:
            try:
                context = self.get_context_data(**kwargs)
            except Exception as e:
                logger.exception(e)
                raise

            context["form"] = form
            context["errors_detected"] = form.is_valid()

        return render(request, self.template_name, context)


    def get(self, request, *args, **kwargs):
        try:
            context = self.get_context_data(**kwargs)
        except Exception as e:
            logger.exception(e)
            raise

        if "node_name" not in context:
            return render(request, self.template_name, context)  # Prints a firendy No Nodes found error

        post_id = view_helpers.check_invoice(memo=context.get("memo"), node_id=context.get("node_id"))
        if post_id:
            return view_helpers.post_redirect(pid=post_id, request=request, permanent=False)

        return super(VotePublishView, self).get(request, *args, **kwargs)
