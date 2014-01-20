from functools import wraps
from http.client import OK, CREATED, BAD_REQUEST
import logging
# from bootstrap.future import SessionWizardView

from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib.formtools.wizard.views import SessionWizardView
from django.core import mail
from django.core.urlresolvers import reverse
from django.forms.models import inlineformset_factory
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import render_to_response, render
from django.forms.formsets import formset_factory
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView, ListView
from django.template import RequestContext
from django.views.decorators.http import require_POST
from flatblocks.models import FlatBlock

from orders import models
from orders.forms import CartItemForm, OrderItemFormset
from orders.models import OrdersEnabled
from orders.utils import get_ingredient
from orders.utils import add_gst

log = logging.getLogger(__name__)


def orders_enabled(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if OrdersEnabled.is_enabled():
            return view(request, *args, **kwargs)
        message = "Sorry, we're not currently taking orders, keep an eye on our facebook page."
        return render(
            request,
            'orders/orders_disabled.html',
            {'error': message},
            status=BAD_REQUEST)
    return wrapper


def main(request):
    return render_to_response('orders/main.html', context_instance=RequestContext(request))


def create_cart_formset(request, user_order=None):
    cart = _get_cart_from_session(request)
    initial = [dict(ingredient=get_ingredient(name), quantity=q) for name, q in cart.items()]
    Formset = inlineformset_factory(
        models.UserOrder,
        models.OrderItem,
        formset=OrderItemFormset,
        extra=len(initial),
        max_num=len(initial),
        fields=("quantity", "ingredient"),
        widgets={
            "ingredient": forms.HiddenInput(),
            "quantity": forms.HiddenInput(),
        })
    data = request.POST if request.POST else None
    if not user_order:
        user_order = models.UserOrder(user=request.user)
    cart_formset = Formset(
        data=data,
        instance=user_order,
        initial=initial,
        prefix="cart")
    return cart_formset


class OrderIngredientView(TemplateView):
    http_method_names = ['get', 'post']
    model = None

    @staticmethod
    def _update_session(formset, request):
        if formset.is_valid():
            for cleaned_data in formset.cleaned_data:
                quantity = cleaned_data.get("quantity", 0)
                ingredient_name = cleaned_data.get("ingredient_name")
                cart = _get_cart_from_session(request)
                if quantity and quantity > 0:
                    cart[ingredient_name] = quantity + cart.get(ingredient_name, 0)
                    request.session.modified = True

    @method_decorator(login_required)
    @method_decorator(orders_enabled)
    def get(self, request, *args, **kwargs):
        ingredient_formset = self.formset_class(initial=self.initial, prefix="ingredients")
        cart_formset = create_cart_formset(request)
        return render(
            request,
            'orders/ingredient_list.html', {
                'title': self.title,
                'ingredient_formset': ingredient_formset,
                'cart_formset': cart_formset})

    @method_decorator(login_required)
    @method_decorator(orders_enabled)
    def post(self, request, *args, **kwargs):
        formset = self.formset_class(request.POST, initial=self.initial, prefix="ingredients")
        if formset.is_valid():
            self.__class__._update_session(formset, request)
            return HttpResponseRedirect('')
        return render(
            request,
            'orders/ingredient_list.html', {
                'title': self.title,
                'ingredient_formset': formset},
            status=BAD_REQUEST)

    @property
    def initial(self):
        return [dict(ingredient_name=i.name, quantity=0, unit_cost=i.unit_cost, unit_size=i.unit_size) for i in self.model.objects.all()]

    @property
    def formset_class(self):
        return formset_factory(CartItemForm, max_num=len(self.initial))

    @property
    def title(self):
        return self.__class__.__name__


class Grains(OrderIngredientView):
    model = models.Grain


class Hops(OrderIngredientView):
    model = models.Hop


@require_POST
@login_required
def review_order(request):
    cart_formset = create_cart_formset(request)
    return render(request, 'orders/review_cart.html', {'cart_formset': cart_formset})


@require_POST
@login_required
def checkout(request):
    # ToDo: check that order has been reviewed!
    # ToDo: Email user a summary
    user_order = models.UserOrder.objects.create(user=request.user)
    formset = create_cart_formset(request, user_order)
    if formset.is_valid():
        formset.save()
        del request.session['cart']
        _email_order_confirmation(request, user_order)
        return HttpResponseRedirect(redirect_to=reverse('order_complete', args=(formset.instance.id,)))
    user_order.delete()
    # ToDo: email admin on failure
    return HttpResponseBadRequest('Could not complete your order')


def _email_order_confirmation(request, user_order):
    message = FlatBlock.objects.get(slug='orders.email.confirmation').content % dict(
        order_number=user_order.id,
        total=add_gst(user_order.total),
    )
    mail.send_mail(
        'Your UCBC Order #%d' % user_order.id,
        message,
        None,
        [request.user.email,],
        fail_silently=True)


def order_complete(request, order_id):
    return render(request, 'orders/order_complete.html', {'order_id': order_id})


@require_POST
@login_required
def cart_delete_item(request):
    cart = _get_cart_from_session(request)
    try:
        ingredient_id = int(request.POST.get('ingredient_id'))
        ingredient_name = models.Ingredient.objects.get(id=ingredient_id).name
        if ingredient_name in cart:
            del cart[ingredient_name]
            request.session.modified = True
    except KeyError:
        log.error("cart_delete_item: no ingredient_id key in POST data. POST: %s" % request.POST)
    if 'HTTP_REFERER' in request.META:
        return HttpResponseRedirect(request.META.get('HTTP_REFERER'))
    return HttpResponse()


class SupplierOrderWizard(SessionWizardView):
    template_name = 'orders/supplier_order_wizard_form.html'
    def done(self, form_list, **kwargs):
        supplier = form_list[0].cleaned_data.get('supplier')
        order = models.SupplierOrder.objects.create(supplier=supplier)
        order_items = form_list[1].cleaned_data.get('ingredient_orders')
        for item in order_items:
            item.supplier_order = order
            item.save()
        return HttpResponseRedirect(
            reverse('orders.views.supplier_order', kwargs=dict(order_id=order.id)))


def supplier_order(request, order_id):
    order = models.SupplierOrder.objects.get(id=order_id)
    return render_to_response('orders/supplier_order.html', {
            'order': order,
        })


class SupplierOrderList(ListView):
    def get_queryset(self):
        supplier_orders = models.SupplierOrder.objects.filter(status=models.SupplierOrder.STATUS_PENDING)
        for supplier in models.Supplier.objects.all():
            order, _ = supplier_orders.get_or_create(supplier=supplier)
            models.OrderItem.objects.filter(
                supplier_order=None,
                ingredient__supplier=supplier).update(supplier_order=order)
        return models.SupplierOrder.objects.filter(status=models.SupplierOrder.STATUS_PENDING)



def _get_cart_from_session(request):
    return request.session.setdefault('cart', {})
